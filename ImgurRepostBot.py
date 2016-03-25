from ImgurRepostDB import ImgurRepostDB
from imgurpython import ImgurClient
from ConfigManager import ConfigManager
from imgurpython.helpers.error import ImgurClientError, ImgurClientRateLimitError
from Dhash import dhash
from urllib import request
from urllib.error import HTTPError
from PIL import Image
from io import BytesIO
import threading
import time
import os
import logging
from distance import hamming

# TODO Common memes with small text get flagged as repost.  Need to increase to 128+ bit hash
# TODO Remove spawn_hash_check_thread

class ImgurRepostBot():

    def __init__(self, detected_reposts=None):

        self.hash_queue = []  # Store unchecked hashes for batch processing
        self.failed_downvotes = []  # Store failed downvotes for later processing
        self.failed_comments = []  # Store failed comments for later processing
        self.last_hash_flush = round(time.time())
        self.delay_between_requests = 5  # Changed on the fly depending on remaining credits and time until reset
        self.thread_lock = threading.Lock()
        self.processed_ids = []
        self.records = []
        self.logger = None

        if not detected_reposts:
            self.detected_reposts = []
        else:
            self.detected_reposts = detected_reposts

        self.config = ConfigManager()
        self._setup_logging()

        self.imgur_client = ImgurClient(self.config.api_details['client_id'],
                                        self.config.api_details['client_secret'],
                                        self.config.api_details['access_token'],
                                        self.config.api_details['refresh_token'])

        self.db_conn = ImgurRepostDB(self.config.mysql_details['user'],
                                     self.config.mysql_details['password'],
                                     self.config.mysql_details['host'],
                                     self.config.mysql_details['database'])

        if self.config.backfill:
            self.backfill_progress = 1
        else:
            self.backfill_progress = 'Disabled'

        threading.Thread(target=self._load_existing_records, name='RecordLoader').start()

        if self.config.backfill:
            threading.Thread(target=self._backfill_database, name='Backfill').start()

        threading.Thread(target=self._hash_processing_thread, name='HashProcessing').start()


    def _check_thread_status(self):

        thread_names = ['configmonitor', 'backfill', 'hashprocessing']

        for thrd in threading.enumerate():
            if thrd.name.lower() in thread_names:
                thread_names.remove(thrd.name.lower())

        for i in thread_names:

            if i == 'configmonitor':
                msg = 'Config Monitor Thread Crashed'
                self._output_error(msg)
                self.config = ConfigManager()
                continue

            if i == 'backfill' and self.config.backfill:
                msg = 'Backfill Thread Crashed'
                self._output_error(msg)
                threading.Thread(target=self._backfill_database, name='Backfill').start()
                continue

            if i == 'hashprocessing':
                msg = 'Hash Processing Thread Crashed'
                self._output_error(msg)
                threading.Thread(target=self._hash_processing_thread, name='HashProcessing').start()
                continue


    def _setup_logging(self):

        if self.config.logging:
            print('Setting Up Logger')
            self.logger = logging.getLogger()
            self.logger.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
            fhandle = logging.FileHandler('botlog.log')
            fhandle.setFormatter(formatter)
            self.logger.addHandler(fhandle)

    def _load_existing_records(self):
        """
        Spawns a thread to load all records from the database.  This allows us to start getting new images without
        waiting on the DB to return records
        :return: None
        """
        records, image_ids = self.db_conn.build_existing_ids()
        try:
            self.thread_lock.acquire()
            self.processed_ids = image_ids
            self.records = records
        finally:
            self.thread_lock.release()

    def _output_error(self, msg):

        print(msg)
        if self.config.logging:
            self.logger.error(msg)

    def _output_info(self, msg):
        print(msg)
        if self.config.logging:
            self.logger.info(msg)

    def _backfill_database(self):
        """
        Backfill the database with older posts.  Useful if script hasn't been run in some time"
        :return:
        """

        current_page = self.config.backfill_start_page
        while current_page < self.config.backfill_depth + self.config.backfill_start_page:

            if not self.db_conn.records_loaded:
                continue

            self.backfill_progress = current_page
            self.insert_latest_images(page=current_page, backfill=True)
            current_page += 1
            time.sleep(2)

        self.backfill_progress = 'Completed'

    def _generate_hash(self, img, hash_size=8):
        """
        Generate the dhash of the provided image.
        """
        results = {}
        results['hash16'] = dhash(img, hash_size=8)
        results['hash64'] = dhash(img, hash_size=16)
        results['hash256'] = dhash(img, hash_size=32)
        return results


    def _generate_img(self, url=None):
        """
        Generate the image files provided from Imgur.  We pass the data straight from the request into PIL.Image
        """

        img = None
        if not url:
            return None

        try:
            response = request.urlopen(url)
            img = Image.open(BytesIO(response.read()))
        except (HTTPError, ConnectionError, OSError) as e:
            msg = 'Error Generating Image File: \n Error Message: {}'.format(e)
            self._output_error(msg)

            return None

        return img if img else None

    def check_for_repost(self, hash_to_check, image_id=None, user=None):

        results = []

        hash_size = 'hash' + self.config.hash_size
        for r in self.records:

            if image_id == r['image_id'] or r['user'] == user:
                continue

            hamming_distance = hamming(hash_to_check[hash_size], r[hash_size])

            if hamming_distance < self.config.hamming_cutoff:
                print('Detected repost')
                results.append(r)


        return results

    def generate_latest_images(self, section='user', sort='time', page=0):

        self._adjust_rate_limit_timing()

        items = []
        try:
            temp = self.imgur_client.gallery(section=section, sort=sort, page=page, show_viral=False)
            if temp:
                items = [i for i in temp if not i.is_album and not self.check_post_title(title=i.title)]
        except (ImgurClientError, ImgurClientRateLimitError) as e:
            msg = 'Error Getting Gallery: {}'.format(e)
            self._output_error(msg)

        return items

    def insert_latest_images(self, section='user', sort='time', page=0, backfill=False):
        """
        Pull all current images from user sub, get the hashes and insert into database.
        """

        # Don't start inserts until all records are loaded
        if not self.db_conn.records_loaded:
            return

        items = self.generate_latest_images(section=section, sort=sort, page=page)

        if not items:
            return

        # Don't add again if we have already done this image ID
        for item in items:
            if item.id in self.processed_ids:
                continue

            img = self._generate_img(url=item.link)
            if img:
                image_hash = self._generate_hash(img)
                if image_hash:

                    record = {
                        'image_id': item.id,
                        'url': item.link,
                        'user': item.account_url,
                        'submitted': item.datetime,
                        'hash16': image_hash['hash16'],
                        'hash64': image_hash['hash64'],
                        'hash256': image_hash['hash256']
                    }

                    self.processed_ids.append(item.id)
                    self.records.append(record)

                    # If this is called from back filling don't add hash to be checked
                    if not backfill:
                        self.hash_queue.append({"hash": image_hash, "image_id": item.id, "user": item.account_url})
                        print('Insert {}'.format(item.link))
                    else:
                        print('Backfill Insert {}'.format(item.link))

                    self.db_conn.add_entry(item.link, image_hash, item.account_url, item.id, item.datetime)

    def downvote_repost(self, image_id):
        """
        Downvote the provided Image ID
        """
        try:
            self.imgur_client.gallery_item_vote(image_id, vote="down")
        except ImgurClientError as e:
            self.failed_downvotes.append(image_id)
            msg = 'Error Voting: {}'.format(e)
            self._output_error(msg)

    def comment_repost(self, image_id=None, values=None):
        """
        Leave a comment on the detected repost.
        :param image_id: ID of image to leave comment on.
        :param values: Values to be inserted into the message template
        :return:
        """

        self._output_info('Leaving Comment On {}'.format(image_id))

        message = self.build_comment_message(values=values)

        try:
            self.imgur_client.gallery_comment(image_id, message)
        except (ImgurClientError, ImgurClientRateLimitError) as e:
            self.failed_comments.append({'image_id': image_id, 'values': values})
            msg = 'Error Posting Commment: {}'.format(e)
            self._output_error(msg)

    def build_comment_message(self, values=None):
        """
        Build the message to use in the comment.

        We first parse the comment template look for {} to count how many custom values we need to insert.   We make
        sure the number we find matches the number in the values arg.

        Example Comment Template: Detected Reposted Image with ID {} and Hash {}
        Example Values: ['s78sdfy', '31b132726521b372]
        """

        # Make sure we got a list
        if values and isinstance(values, list):
            total_values = len(values)
        else:
            total_values = 0

        format_count = 0
        for i in self.config.comment_template:
            if i == '{':
                format_count += 1

        # If there are no format options return the raw template
        if format_count == 0:
            return self.config.comment_template

        if not format_count == total_values:
            msg = 'Provided Values Do Not Match Format Places In Comment Template\n ' \
                  'Format Spots: {} \nProvided Values: {}'.format(format_count, total_values)
            self._output_error(msg)
            return self.config.comment_template

        return self.config.comment_template.format(*values)

    def flush_failed_votes_and_comments(self):
        """
        If there have been any failed votes or comments (due to imgur server overload) try to redo them
        """

        if self.failed_downvotes:
            for image_id in self.failed_downvotes:
                try:
                    self.imgur_client.gallery_item_vote(image_id, vote="down")
                    self.failed_downvotes.remove(image_id)
                except (ImgurClientError, ImgurClientRateLimitError) as e:
                    msg = 'Failed To Retry Downvote On Image {}.  \nError: {}'.format(image_id, e)
                    self._output_error(msg)

        if self.failed_comments:
            for failed in self.failed_comments:
                try:
                    message = self.build_comment_message(values=failed['values'])
                    self.imgur_client.gallery_comment(failed['image_id'], message)
                    self.failed_comments.remove(failed['image_id'])
                except (ImgurClientError, ImgurClientRateLimitError) as e:
                    msg = 'Failed To Retry Comment On Image {}.  \nError: {}'.format(failed['image_id'], e)
                    self._output_error(msg)

    def _hash_processing_thread(self):

        while True:
            if len(self.hash_queue) > 0 and self.db_conn.records_loaded:

                current_hash = self.hash_queue.pop(0)

                result = self.check_for_repost(current_hash['hash'],
                                                                 image_id=current_hash['image_id'],
                                                                 user=current_hash['user'])

                if result:

                    msg = 'Found Reposted Image: https://imgur.com/gallery/{}'.format(current_hash['image_id'])
                    self._output_info(msg)

                    if self.config.leave_downvote:
                        self.downvote_repost(current_hash['image_id'])

                    # TODO Need to think of a better way to do the comments.  Needs to be more easily user customizable
                    if self.config.leave_comment:
                        message_values = []
                        message_values.append(len(result))
                        message_values.append(current_hash['hash'])
                        self.comment_repost(image_id=current_hash['image_id'], values=message_values)

                    matching_images = []
                    for r in result:
                        print('Original: https://imgur.com/gallery/{}'.format(r['image_id']))
                        matching_images.append('https://imgur.com/gallery/{}'.format(r['image_id']))

                    self.detected_reposts.append({"image_id": current_hash['image_id'], "original_image": matching_images})

                    if self.config.log_reposts:
                        self.log_repost(repost_url='https://imgur.com/gallery/{}'.format(current_hash['image_id']),
                                        matching_images=matching_images)



    def log_repost(self, repost_url=None, matching_images=None):
        """
        Log the reposted image out to a file.  Also include all matching images we found
        """
        log_file = os.path.join(os.getcwd(), "repost.log")  # TODO Move to config

        if repost_url and matching_images:
            with open(log_file, 'a+') as log:
                log.write('Repost Image: {}\n'.format(repost_url))
                log.write('Matching Images: \n')
                for img in matching_images:
                    log.write('- {}\n'.format(img))
                log.write('\n\n')


    def _adjust_rate_limit_timing(self):
        """
        Adjust the timing used between request to spread all requests over allowed rate limit

        """

        # API Fails To Return This At Times
        if not self.imgur_client.credits['ClientRemaining']:
            return

        remaining_credits_before = int(self.imgur_client.credits['ClientRemaining'])
        self.imgur_client.credits = self.imgur_client.get_credits()  # Refresh the credit data

        # Imgur API sometimes returns 12500 credits remaining in error.  If this happens don't update request delay.
        # Otherwise the delay will drop to the minimum set in the config and can cause premature credit exhaustion
        if int(self.imgur_client.credits['ClientRemaining']) - remaining_credits_before > 100:
            """
            print('Imgur API Returned Wrong Remaining Credits.  Keeping Last Request Delay Time')
            print('API Credits: ' + str(self.imgur_client.credits['ClientRemaining']))
            print('Last Credits: ' + str(remaining_credits_before))
            """
            return

        remaining_credits = self.imgur_client.credits['ClientRemaining']
        reset_time = self.imgur_client.credits['UserReset'] + 240  # Add a 4 minute buffer so we don't cut it so close
        remaining_seconds = reset_time - round(time.time())
        seconds_per_credit = round(remaining_seconds / remaining_credits)  # TODO Getting division by zero sometimes

        if seconds_per_credit < self.config.min_time_between_requests:
            self.delay_between_requests = self.config.min_time_between_requests
        else:
            self.delay_between_requests = seconds_per_credit

    def check_post_title(self, title=None):
        """
        Checks the post title for values that we will use to skip over it
        This allows us not to flag MRW posts and others as reposts
        :return:
        """

        if not title:
            return None

        return [v for v in self.config.title_check_values if v in title.lower()]


    def print_current_settings(self):


            print('** Current Settings **')
            print('Leave Comments: {}'.format(self.config.leave_comment))
            print('Leave Downvote: {} '.format(self.config.leave_downvote))
            print('Do Backfill: {} '.format(self.config.backfill))
            print('Hash Size: {}'.format(self.config.hash_size))
            print('Hamming Distance: {}'.format(self.config.hamming_cutoff))

    def run(self):

        last_run = round(time.time())

        while True:

            os.system('cls')

            print('** Current Stats **')
            print('Total Pending Hashes To Check: {}'.format(str(len(self.hash_queue))))
            print('Total processed images: {}'.format(str(len(self.processed_ids))))
            print('Total Reposts Found: {}'.format(str(len(self.detected_reposts))))
            print('Backfill Progress: {}'.format(str(self.backfill_progress)))
            print('Yes' if self.db_conn.records_loaded else 'No')

            self.print_current_settings()

            print('** API Settings **')
            print('Remaining Credits: {}'.format(self.imgur_client.credits['ClientRemaining']))
            if self.imgur_client.credits['UserReset']:
                print('Minutes Until Credit Reset: {}'.format(round((int(self.imgur_client.credits['UserReset']) - time.time()) / 60)))

            # Make it clear we are overriding the default delay to meet credit refill window
            if self.delay_between_requests == self.config.min_time_between_requests:
                request_delay = self.delay_between_requests
            else:
                request_delay = str(self.delay_between_requests) + ' (Overridden By Rate Limit)'
            print('Delay Between Requests: {}\n'.format(request_delay))

            print('Running Threads: ')
            for thrd in threading.enumerate():
                if thrd.name.lower() == 'mainthread':
                    continue
                print('[+] ', thrd.name)

            if round(time.time()) - last_run > self.delay_between_requests:
                self.insert_latest_images()
                self.flush_failed_votes_and_comments()
                last_run = round(time.time())

            time.sleep(2)


def main():

    # TODO This is sloppy.  Quick way to keep it running when I'm not watching it


    while True:
        try:
            rcheck = ImgurRepostBot()
            rcheck.run()
        except Exception as ex:
            msg = 'An Exception Occurred During Execution.  Flushing Remaining Hashes\n Exception Type {}'.format(type(ex))
            with open('ex_error.log', 'a+') as f:
                f.write(msg)

if __name__ == '__main__':              # if we're running file directly and not importing it
    main()