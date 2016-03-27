from ImgurRepostDB import ImgurRepostDB
from imgurpython import ImgurClient
from ConfigManager import ConfigManager
from imgurpython.helpers.error import ImgurClientError, ImgurClientRateLimitError
from urllib import request
from urllib.error import HTTPError
from PIL import Image
from io import BytesIO
import threading
import time
import os
import logging
from ImgurHashProcessing import HashProcessing

class ImgurRepostBot():

    def __init__(self):

        os.system('cls')
        self.failed_downvotes = []  # Store failed downvotes for later processing
        self.failed_comments = []  # Store failed comments for later processing
        self.last_hash_flush = round(time.time())
        self.delay_between_requests = 5  # Changed on the fly depending on remaining credits and time until reset
        self.thread_lock = threading.Lock()
        self.logger = None
        self.detected_reposts = 0


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

        self.backfill_progress = 1 if self.config.backfill else 'Disabled'


        records, processed_ids = self.db_conn.build_existing_ids()

        if self.config.backfill:
            threading.Thread(target=self._backfill_database, name='Backfill').start()

        self.hash_processing = HashProcessing(self.config, processed_ids, records)

        threading.Thread(target=self._repost_processing_thread, name='RepostProcessing').start()



    def _check_thread_status(self):
        """
        Check status of critical threads.  If they are found dead start them back up
        :return:
        """
        thread_names = ['configmonitor', 'backfill', 'repostprocessing']

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

            if i == 'repostprocessing':
                msg = 'Repost Processing Thread Crashed'
                self._output_error(msg)
                threading.Thread(target=self._repost_processing_thread, name='RepostProcessing').start()
                continue

    def _setup_logging(self):

        if self.config.logging:
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.ERROR)
            formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
            fhandle = logging.FileHandler('botlog.log')
            fhandle.setFormatter(formatter)
            self.logger.addHandler(fhandle)

    def _output_error(self, msg, output=True):
        """
        convenience method to log and/or print an error
        :param msg: Message to output/log
        :param output: Print error to console
        :return:
        """
        if output:
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

        while True:
            original_start_page = self.config.backfill_start_page # So we can detect if it's changed in the config
            current_page = self.config.backfill_start_page
            while current_page < self.config.backfill_depth + self.config.backfill_start_page:

                if not self.db_conn.records_loaded:
                    continue

                self.backfill_progress = current_page
                self.insert_latest_images(page=current_page, backfill=True)
                current_page += 1
                time.sleep(2)

                if self.config.backfill_start_page != original_start_page:
                    print('Backfill Start Page Changed In Config')
                    break

            self.backfill_progress = 'Completed'
            break

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
            if item.id in self.hash_processing.processed_ids:
                continue

            img = self._generate_img(url=item.link)
            if img:
                image_hash = self.hash_processing.generate_hash(img)
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

                    self.hash_processing.processed_ids.append(item.id)
                    self.hash_processing.records.append(record)

                    # If this is called from back filling don't add hash to be checked
                    if not backfill:
                        self.hash_processing.hash_queue.append(record)
                        print('Insert {}'.format(item.link))
                    else:
                        print('Backfill Insert {}'.format(item.link))

                    self.db_conn.add_entry(record)

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

    def _repost_processing_thread(self):
        """
        Runs in background monitor the queue for detected reposts
        :return:
        """
        while True:
            if len(self.hash_processing.repost_queue) > 0:
                current_repost = self.hash_processing.repost_queue.pop(0)
                if self.config.leave_downvote:
                    self.downvote_repost(current_repost['image_id'])


                self.detected_reposts += 1
                # TODO add comment handling.  Records in repost queue need to be sorted to identify oldest post

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
        print('Current Settings')
        print('[+] Leave Comments: {}'.format(self.config.leave_comment))
        print('[+] Leave Downvote: {} '.format(self.config.leave_downvote))
        print('[+] Do Backfill: {} '.format(self.config.backfill))
        print('[+] Hash Size: {} bit'.format(self.config.hash_size))
        print('[+] Hamming Distance: {}{}'.format(self.config.hamming_cutoff, '\n'))


    def print_current_stats(self):
        print('Current Stats')
        print('[+] Total Hashes Waiting In Pool: {}'.format(str(self.hash_processing.total_in_queue)))
        print('[+] Total Hashes In Hash Queue: {}'.format(str(len(self.hash_processing.hash_queue))))
        print('[+] Total processed images: {}'.format(str(len(self.hash_processing.processed_ids))))
        print('[+] Total Reposts Found: {}'.format(str(self.detected_reposts)))
        print('[+] Backfill Progress: {}{}'.format(str(self.backfill_progress), '\n'))


    def print_api_stats(self):
        print('API Settings')
        print('[+] Remaining Credits: {}'.format(self.imgur_client.credits['ClientRemaining']))
        if self.imgur_client.credits['UserReset']:
            print('[+] Time Until Credit Reset: {} Minutes'.format(round((int(self.imgur_client.credits['UserReset']) - time.time()) / 60)))

        # Make it clear we are overriding the default delay to meet credit refill window
        if self.delay_between_requests == self.config.min_time_between_requests:
            request_delay = str(self.delay_between_requests) + ' Seconds'
        else:
            request_delay = str(self.delay_between_requests) + ' Seconds (Overridden By Rate Limit)'
        print('[+] Delay Between Requests: {} \n'.format(request_delay))

    def run(self):

        last_run = round(time.time())

        while True:

            os.system('cls')

            self.print_current_stats()
            self.print_current_settings()
            self.print_api_stats()

            if round(time.time()) - last_run > self.delay_between_requests:
                self.insert_latest_images()
                self.flush_failed_votes_and_comments()
                last_run = round(time.time())

            self._check_thread_status()

            time.sleep(2)


def main():

    # TODO This is sloppy.  Quick way to keep it running when I'm not watching it

    rcheck = ImgurRepostBot()
    rcheck.run()
    """
    while True:
        try:
            rcheck = ImgurRepostBot()
            rcheck.run()
        except Exception as ex:
            msg = 'An Exception Occurred During Execution.  Flushing Remaining Hashes\n Exception Type {}'.format(type(ex))
            with open('ex_error.log', 'a+') as f:
                f.write(msg)
    """
if __name__ == '__main__':              # if we're running file directly and not importing it
    main()