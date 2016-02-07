from ImgurRepostDB import ImgurRepostDB
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError, ImgurClientRateLimitError
from Dhash import dhash
from urllib import request
from urllib.error import HTTPError
from PIL import Image
from io import BytesIO
import threading
import time
import configparser
import os
import sys

# TODO Common memes with small text get flagged as repost.  Need to increase to 128+ bit hash

class ImgurRepostBot():

    def __init__(self):

        self.detected_reposts = []
        self.hashes_to_check = []  # Store unchecked hashes for batch processing
        self.failed_downvotes = []  # Store failed downvotes for later processing
        self.failed_comments = []  # Store failed comments for later processing
        self.last_hash_flush = round(time.time())
        self.config_file = os.path.join(os.getcwd(), 'bot.ini')
        self.config_last_modified = round(os.path.getmtime(self.config_file))
        self.delay_between_requests = 5  # Changed on the fly depending on remaining credits and time until reset


        # General Options - Can be overridden from ini file
        self.leave_comment = False
        self.leave_downvote = False
        self.log_reposts = False
        self.backfill = False
        self.backfill_depth = 500
        self.hash_flush_interval = 20
        self.min_time_between_requests = 5
        self.title_check_values = ['mrw', 'when', 'my reaction']
        self.comment_template = "We Have Detected Reposted Content.  Reference Hash: {}"

        # Load The Config.  If We Can't Find It Abort
        if os.path.isfile(self.config_file):
            config = configparser.ConfigParser()
            config.read(self.config_file)
            self._verify_ini(config_file=config)
        else:
            print('ERROR: Unable To Load ini File.  Ensure bot.ini is in the CWD')
            sys.exit(1)

        self.imgur_client = ImgurClient(config['IMGURAPI']['ClientID'], config['IMGURAPI']['ClientSecret'],
                                        config['IMGURAPI']['AccessToken'], config['IMGURAPI']['RefreshToken'])


        self.db_conn = ImgurRepostDB(config['MYSQL']['User'], config['MYSQL']['Password'], config['MYSQL']['Host'],
                                     config['MYSQL']['Database'])

        # Pull all previous images from DB so we can compare image IDs without hitting DB each time
        self.processed_images = self.db_conn.build_existing_ids()

        self._set_ini_options(config)

        if self.backfill:
            threading.Thread(target=self._backfill_database, name='Backfill').start()


    def _backfill_database(self):
        """
        Backfill the database with older posts.  Useful if script hasn't been run in some time"
        :return:
        """

        current_page = 1
        while current_page < self.backfill_depth:
            self.insert_latest_images(page=current_page, backfill=True)
            current_page += 1
            time.sleep(self.delay_between_requests)



    def _set_ini_options(self, config):
        """
        Set the optional values found in the ini
        """

        # Load Options From Config
        if 'LeaveComment' in config['OPTIONS']:
            self.leave_comment = config['OPTIONS'].getboolean('LeaveComment')

        if 'DownVote' in config['OPTIONS']:
            self.leave_downvote = config['OPTIONS'].getboolean('Downvote')

        if 'FlushInterval' in config['OPTIONS']:
            self.hash_flush_interval = int(config['OPTIONS']['FlushInterval'])

        if 'CommentTemplate' in config['OPTIONS']:
            self.comment_template = config['OPTIONS']['CommentTemplate']

        if 'MinTimeBetweenRequests' in config['OPTIONS']:
            self.min_time_between_requests = int(config['OPTIONS']['MinTimeBetweenRequests'])

        if 'LogReposts' in config['OPTIONS']:
            self.log_reposts = config['OPTIONS'].getboolean('LogReposts')

        if 'Backfill' in config['OPTIONS']:
            self.backfill = config['OPTIONS'].getboolean('Backfill')

        if 'BackfillDepth' in config['OPTIONS']:
            self.backfill_depth = int(config['OPTIONS']['BackfillDepth'])

        if 'ExcludeInTitle' in config['OPTIONS']:
            temp = config['OPTIONS']['CommentTemplate'].split(',')

            # Cleanup Any Spaces Added To Start Or End Of Values.  God help us if they add more than 1
            for val in temp:
                if val[0] == ' ':
                    val = val[1:]
                if val[-1] == ' ':
                    val = val[0:len(val) - 1]

                self.title_check_values.append(val.lower())


    def _verify_ini(self, config_file=None):
        """
        Make sure all required fields are in the config file.  If they are not, abort the script
        """

        imgur_values = ['ClientID', 'ClientSecret', 'AccessToken', 'RefreshToken']
        mysql_values = ['Host', 'User', 'Password', 'Database']
        missing_values = []

        if not config_file:
            print("No Config Filed Supplied.  Aborting")
            sys.exit(1)

        for val in imgur_values:
            if val not in config_file['IMGURAPI']:
                missing_values.append('IMGURAPI: ' + val)

        for val in mysql_values:
            if val not in config_file['MYSQL']:
                missing_values.append('MYSQL: ' + val)

        if missing_values:
            print('ERROR: ini file is missing required values. \n Missing Values:')
            for val in missing_values:
                print(val)
            sys.exit(1)

    def reload_ini(self):
        """
        Check if the config has been updated.  If it has reload it.
        """

        if round(os.path.getmtime(self.config_file)) > self.config_last_modified:
            print('Config Changes Detected, Reloading .ini File')
            config = configparser.ConfigParser()
            config.read(self.config_file)
            self._set_ini_options(config)
            self.config_last_modified = round(os.path.getmtime(self.config_file))

    def _generate_hash(self, img, hash_size=8):
        """
        Generate the dhash of the provided image.
        """
        return dhash(img, hash_size=hash_size)


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
        except (HTTPError, OSError) as e:
            print('Error Generating Image File: \n Error Message: {}'.format(e))
            return None

        return img if img else None

    def check_for_repost(self, hash_to_check, image_id, user):
        return self.db_conn.check_repost(hash_to_check, image_id, user)

    def generate_latest_images(self, section='user', sort='time', page=0):

        self._adjust_rate_limit_timing()

        items = []
        try:
            temp = self.imgur_client.gallery(section=section, sort=sort, page=page, show_viral=False)
            if temp:
                items = [i for i in temp if not i.is_album and not self.check_post_title(title=i.title)]
        except (ImgurClientError, ImgurClientRateLimitError) as e:
            print('Error Getting Gallery: {}'.format(e))

        return items

    def insert_latest_images(self, section='user', sort='time', page=0, backfill=False):
        """
        Pull all current images from user sub, get the hashes and insert into database.
        """
        items = self.generate_latest_images(section=section, sort=sort, page=page)

        if not items:
            return

        # Don't add again if we have already done this image ID
        for item in items:
            if item.id in self.processed_images:
                continue

            img = self._generate_img(url=item.link)
            if img:
                image_hash = self._generate_hash(img)
                if image_hash:
                    self.processed_images.append(item.id)
                    # If this is called from back filling doing add hash to be checked
                    if not backfill:
                        self.hashes_to_check.append({"hash": image_hash, "image_id": item.id, "user": item.account_url})
                        print('Insert {}'.format(item.link))
                    else:
                        print('Backfill Insert {}'.format(item.link))
                    self.db_conn.add_entry(item.link, image_hash, item.account_url, item.id)

    def downvote_repost(self, image_id):
        """
        Downvote the provided Image ID
        """
        try:
            self.imgur_client.gallery_item_vote(image_id, vote="down")
        except ImgurClientError as e:
            self.failed_downvotes.append(image_id)
            print('Error Voting: {}'.format(e))

    def comment_repost(self, image_id=None, values=None):
        """
        Leave a comment on the detected repost.
        :param image_id: ID of image to leave comment on.
        :param values: Values to be inserted into the message template
        :return:
        """

        print('Leaving Comment On {}'.format(image_id))

        message = self.build_comment_message(values=values)

        try:
            self.imgur_client.gallery_comment(image_id, message)
        except (ImgurClientError, ImgurClientRateLimitError) as e:
            self.failed_comments.append({'image_id': image_id, 'values': values})
            print('Error Posting Commment: {}'.format(e))

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
        for i in self.comment_template:
            if i == '{':
                format_count += 1

        # If there are no format options return the raw template
        if format_count == 0:
            return self.comment_template

        if not format_count == total_values:
            print('Provided Values Do Not Match Format Places In Comment Template')
            print('Format Spots: {} \nProvided Values: {}'.format(format_count, total_values))
            return self.comment_template

        return self.comment_template.format(*values)

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
                    print('Failed To Retry Downvote On Image {}.  \nError: {}'.format(image_id, e))

        if self.failed_comments:
            for failed in self.failed_comments:
                try:
                    message = self.build_comment_message(values=failed['values'])
                    self.imgur_client.gallery_comment(failed['image_id'], message)
                    self.failed_comments.remove(failed['image_id'])
                except (ImgurClientError, ImgurClientRateLimitError) as e:
                    print('Failed To Retry Comment On Image {}.  \nError: {}'.format(failed['image_id'], e))

    def flush_stored_hashes(self, hashes_to_check=None):
        """
        Flush all hashes we have stored up.  When we flush we compare each hash against the database to see if it's a
        repost.

        :param force_quit: When true we ignore the flush interval and do the flush regardless.
        """

        print('Running Hash Checks')
        self.last_hash_flush = round(time.time())
        for current_hash in hashes_to_check:

            #print('Checking Hash {}'.format(current_hash['hash']))
            result, total_detections = self.check_for_repost(current_hash['hash'], current_hash['image_id'], current_hash['user'])

            if result:

                print('Found Reposted Image: https://imgur.com/gallery/{}'.format(current_hash['image_id']))

                if self.leave_downvote:
                    self.downvote_repost(current_hash['image_id'])

                # TODO Need to think of a better way to do the comments.  Needs to be more easily user customizable
                if self.leave_comment:
                    message_values = []
                    message_values.append(len(result))
                    message_values.append(current_hash['hash'])
                    self.comment_repost(image_id=current_hash['image_id'], values=message_values)

                matching_images = []
                for r in result:
                    print('Original: https://imgur.com/gallery/{}'.format(r.image_id))
                    matching_images.append('https://imgur.com/gallery/{}'.format(r.image_id))

                self.detected_reposts.append({"image_id": current_hash['image_id'], "original_image": matching_images})

                if self.log_reposts:
                    self.log_repost(repost_url='https://imgur.com/gallery/{}'.format(current_hash['image_id']),
                                    matching_images=matching_images)

    def spawn_hash_check_thread(self, force_quit=False):

        if round(time.time()) - self.last_hash_flush > self.hash_flush_interval or force_quit:
            hashes = self.hashes_to_check
            self.hashes_to_check = []
            thrd = threading.Thread(target=self.flush_stored_hashes, name='Hash Check Thread',
                                    kwargs={'hashes_to_check': hashes})
            thrd.start()

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
        else:
            print('LOG ERROR: Missing Original URL or Matching Images')
            return


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
            print('Imgur API Returned Wrong Remaining Credits.  Keeping Last Request Delay Time')
            print('API Credits: ' + str(self.imgur_client.credits['ClientRemaining']))
            print('Last Credits: ' + str(remaining_credits_before))
            return

        remaining_credits = self.imgur_client.credits['ClientRemaining']
        reset_time = self.imgur_client.credits['UserReset'] + 240  # Add a 4 minute buffer so we don't cut it so close
        remaining_seconds = reset_time - round(time.time())
        seconds_per_credit = round(remaining_seconds / remaining_credits)  # TODO Getting division by zero sometimes

        if seconds_per_credit < self.min_time_between_requests:
            self.delay_between_requests = self.min_time_between_requests
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

        return [v for v in self.title_check_values if v in title.lower()]

    def run(self):

        while True:

            os.system('cls')

            print('** Current Stats **')
            print('Total Pending Hashes To Check: {}'.format(str(len(self.hashes_to_check))))
            print('Total processed images: {}'.format(str(len(self.processed_images))))
            print('Total Reposts Found: {}\n'.format(str(len(self.detected_reposts))))

            print('** Current Settings **')
            print('Leave Comments: {}'.format(self.leave_comment))
            print('Leave Downvote: {} '.format(self.leave_downvote))
            print('Flush Hashes Every {} Seconds\n'.format(self.hash_flush_interval))

            print('** API Settings **')
            print('Remaining Credits: {}'.format(self.imgur_client.credits['ClientRemaining']))
            if self.imgur_client.credits['UserReset']:
                print('Minutes Until Credit Reset: {}'.format(round((int(self.imgur_client.credits['UserReset']) - time.time()) / 60)))

            # Make it clear we are overriding the default delay to meet credit refill window
            if self.delay_between_requests == self.min_time_between_requests:
                request_delay = self.delay_between_requests
            else:
                request_delay = str(self.delay_between_requests) + ' (Overridden By Rate Limit)'
            print('Delay Between Requests: {}\n'.format(request_delay))

            self.insert_latest_images()
            self.flush_failed_votes_and_comments()
            self.spawn_hash_check_thread()
            self.reload_ini()

            time.sleep(self.delay_between_requests)


def main():
    rcheck = ImgurRepostBot()

    # TODO This is sloppy.  Quick way to keep it running when I'm not watching it
    while True:
        try:
            rcheck.run()
        except:
            print('An Exception Occurred During Execution.  Flushing Remaining Hashes')
            rcheck.spawn_hash_check_thread(force_quit=True)
            rcheck = ImgurRepostBot()



if __name__ == '__main__':              # if we're running file directly and not importing it
    main()