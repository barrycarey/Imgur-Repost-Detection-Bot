from ImgurRepostDB import ImgurRepostDB
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError
from Dhash import dhash
from urllib import request
from urllib.error import HTTPError
from PIL import Image
from io import BytesIO
import time
import configparser
import os
import sys

# TODO Make a customizable comment template

class ImgurRepostBot():

    def __init__(self):

        self.detected_reposts = []
        self.hashes_to_check = []
        self.failed_downvotes = []
        self.failed_comments = []
        self.comment_template = "Repost Nazi Bot has detected reposted content. Downvotes applied! This is an automated system. "

        # General Options - Can be overridden from ini file
        self.leave_comment = False
        self.leave_downvote = False

        # Load The Config.  If We Can't Find It Abort
        config_file = os.path.join(os.getcwd(), 'bot.ini')
        if os.path.isfile(config_file):
            config = configparser.ConfigParser()
            config.read(config_file)
            self._verify_ini(config_file=config)
        else:
            print('ERROR: Unable To Load ini File.  Ensure bot.ini is in the CWD')
            sys.exit(1)

        self.imgur_client = ImgurClient(config['IMGURAPI']['ClientID'], config['IMGURAPI']['ClientSecret'],
                                        config['IMGURAPI']['AccessToken'], config['IMGURAPI']['RefreshToken'])


        self.db_conn = ImgurRepostDB(config['MYSQL']['User'], config['MYSQL']['Password'], config['MYSQL']['Host'],
                                     config['MYSQL']['Database'])

        # Pull all previous images from DB so we can compare image IDs without hitting DB each time
        # TODO We may only need to pull last 24 hours.  Main reason for this is to prevent hitting the same image.
        self.processed_images = self.db_conn.build_existing_ids()

        # Load Options From Config
        if 'LeaveComment' in config['OPTIONS']:
            self.leave_comment = config['OPTIONS']['LeaveComment']

        if 'DownVote' in config['OPTIONS']:
            self.leave_downvote = config['OPTIONS']['Downvote']

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

    def _generate_hash(self, img):
        """
        Generate the dhash of the provided image.
        """
        return dhash(img)


    def _generate_img(self, url=None):
        """
        Generate the image files provided from Imgur.  We pass the data straight from the request into PIL.Image
        :param url:
        :return:
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
        items = []
        try:
            temp = self.imgur_client.gallery(section=section, sort=sort, page=page, show_viral=False)
            if temp:
                items = [i for i in temp if not i.is_album]
        except ImgurClientError as e:
            print("Error Getting Gallery: {}".format(e))

        return items

    def insert_latest_images(self):
        """
        Pull all current images from user sub, get the hash and insert into database.
        """
        items = self.generate_latest_images()

        # Don't add again if we have already done this image ID
        for item in items:
            if item.id in self.processed_images:
                continue

            img = self._generate_img(url=item.link) # Download the image data and convert to PIL image
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
            print("Error Voting: {}".format(e))

    def comment_repost(self, image_id, hash, detections):
        print("Leaving Comment On " + image_id)
        message = self.comment_template
        try:
            self.imgur_client.gallery_comment(image_id, message)
        except ImgurClientError as e:
            self.failed_comments.append(image_id)
            print("Error Posting Commment: {}".format(e))

    def flush_failed_votes_and_comments(self):
        """
        If there have been any failed votes or comments (due to imgur server overload) try to redo them
        """

        if self.failed_downvotes:
            for image_id in self.failed_downvotes:
                try:
                    self.imgur_client.gallery_item_vote(image_id, vote="down")
                    self.failed_downvotes.remove(image_id)
                except ImgurClientError as e:
                    print('Failed To Retry Downvote On Image {}.  \nError: {}'.format(image_id, e))

        if self.failed_comments:
            for image_id in self.failed_comments:
                try:
                    message = self.comment_template
                    self.imgur_client.gallery_comment(image_id, message)
                    self.failed_comments.remove(image_id)
                except ImgurClientError as e:
                    print('Failed To Retry Comment On Image {}.  \nError: {}'.format(image_id, e))


def main():
    rcheck = ImgurRepostBot()
    print(str(len(rcheck.processed_images)))

    count = 0
    while True:
        rcheck.insert_latest_images()
        print("Total Pending Hashes To Check: {}".format(str(len(rcheck.hashes_to_check))))
        print("Total processed images: {}".format(str(len(rcheck.processed_images))))
        print("Total Reposts Found: {}".format(str(len(rcheck.detected_reposts))))

        if count >= 5:
            print("Running Hash Checks")
            for hash in rcheck.hashes_to_check:
                print("Checking Hash {}".format(hash['hash']))
                result, total_detections = rcheck.check_for_repost(hash['hash'], hash['image_id'], hash['user'])
                if result:
                    print("Found Reposted Image: https://imgur.com/gallery/" + hash['image_id'] )
                    if rcheck.leave_downvote:
                        rcheck.downvote_repost(hash['image_id'])
                    if rcheck.leave_comment:
                        rcheck.comment_repost(hash['image_id'], hash['hash'], total_detections)

                    for r in result:
                        print("Original: https://imgur.com/gallery/" + r.image_id)
                        rcheck.detected_reposts.append({"image_id": hash['image_id'], "original_image": r.image_id})
            time.sleep(10)
            rcheck.hashes_to_check = []
            count = 0
            continue
        count += 1
        time.sleep(5)



if __name__ == '__main__':              # if we're running file directly and not importing it
    main()