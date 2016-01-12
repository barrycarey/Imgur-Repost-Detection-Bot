from ImgurRepostDB import ImgurRepostDB
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError, ImgurClientRateLimitError
from Dhash import dhash
from urllib import request
from urllib.error import HTTPError
from PIL import Image
from io import BytesIO
import time
import configparser
import os
import sys

# TODO Common memes with small text get flagged as repost

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
        self.hash_flush_interval = 20
        self.min_time_between_requests = 5
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
            print('Reloading .ini File')
            config = configparser.ConfigParser()
            config.read(self.config_file)
            self._set_ini_options(config)
            self.config_last_modified = round(os.path.getmtime(self.config_file))

    def _generate_hash(self, img):
        """
        Generate the dhash of the provided image.
        """
        return dhash(img)


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

    def check_for_repost(self, hash, image_id, user):
        return self.db_conn.check_repost(hash, image_id, user)

    def generate_latest_images(self, section='user', sort='time', page=0):

        self._adjust_rate_limit_timing()

        items = []
        try:
            temp = self.imgur_client.gallery(section=section, sort=sort, page=page, show_viral=False)
            if temp:
                items = [i for i in temp if not i.is_album]
        except (ImgurClientError, ImgurClientRateLimitError) as e:
            print('Error Getting Gallery: {}'.format(e))

        return items

    def insert_latest_images(self):
        """
        Pull all current images from user sub, get the hashes and insert into database.
        """
        items = self.generate_latest_images()

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
                    self.hashes_to_check.append({"hash": image_hash, "image_id": item.id, "user": item.account_url})
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

    def flush_stored_hashes(self, force_quit=False):
        """
        Flush the hashes that we have stored.
        """

        if round(time.time()) - self.last_hash_flush > self.hash_flush_interval or force_quit:

            print('Running Hash Checks')
            self.last_hash_flush = round(time.time())
            for current_hash in self.hashes_to_check:

                print('Checking Hash {}'.format(current_hash['hash']))
                result, total_detections = self.check_for_repost(current_hash['hash'], current_hash['image_id'], current_hash['user'])

                if result:

                    print('Found Reposted Image: https://imgur.com/gallery/{}'.format(current_hash['image_id']))

                    if self.leave_downvote:
                        self.downvote_repost(current_hash['image_id'])

                    # Need to think of a better way to do the comments.  Needs to be more easily user customizable
                    if self.leave_comment:
                        message_values = []
                        message_values.append(len(result))
                        message_values.append(current_hash['hash'])
                        self.comment_repost(image_id=current_hash['image_id'], values=message_values)

                    for r in result:
                        print('Original: https://imgur.com/gallery/{}'.format(r.image_id))
                        self.detected_reposts.append({"image_id": current_hash['image_id'], "original_image": r.image_id})

            self.hashes_to_check = []

    def _adjust_rate_limit_timing(self):
        """
        Adjust the timing used between request to spread all requests over allowed rate limit

        """
        self.imgur_client.credits = self.imgur_client.get_credits()  # Refresh the credit data

        remaining_credits = self.imgur_client.credits['ClientRemaining']
        reset_time = self.imgur_client.credits['UserReset']
        remaining_seconds = reset_time - round(time.time())
        seconds_per_credit = round(remaining_seconds / remaining_credits)

        print('Raw Seconds Per Credit: {}'.format(seconds_per_credit))

        if seconds_per_credit < self.min_time_between_requests:
            self.delay_between_requests = self.min_time_between_requests
        else:
            self.delay_between_requests = seconds_per_credit


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
            print('Delay Between Requests: {}\n'.format(self.delay_between_requests))

            self.insert_latest_images()
            self.flush_failed_votes_and_comments()
            self.flush_stored_hashes()
            self.reload_ini()

            time.sleep(self.delay_between_requests)


def main():
    rcheck = ImgurRepostBot()

    try:
        rcheck.run()
    except KeyboardInterrupt:
        print('Keyboard Quit Detected.  Flushing Remaining Hashes')
        rcheck.flush_stored_hashes(force_quit=True)



if __name__ == '__main__':              # if we're running file directly and not importing it
    main()