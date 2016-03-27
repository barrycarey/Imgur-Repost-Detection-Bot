__author__ = 'Jeromy'

import os
import sys
import configparser
import time
import threading

class ConfigManager():

    def __init__(self):

        self.config_file = os.path.join(os.getcwd(), 'bot.ini')
        self.config_last_modified = round(os.path.getmtime(self.config_file))

        # General Options - Can be overridden from ini file
        self.leave_comment = False
        self.leave_downvote = False
        self.log_reposts = False
        self.hash_flush_interval = 20
        self.min_time_between_requests = 5
        self.title_check_values = ['mrw', 'when', 'my reaction']
        self.comment_template = "We Have Detected Reposted Content.  Reference Hash: {}"
        self.logging = False
        self.hash_size = 16
        self.hamming_cutoff = 3
        self.hash_proc_limit = 5

        # Backfill settings.  Can be overridden via config
        self.backfill = False
        self.backfill_depth = 500
        self.backfill_start_page = 1


        # Load The Config.  If We Can't Find It Abort
        if os.path.isfile(self.config_file):
            config = configparser.ConfigParser()
            config.read(self.config_file)
            self._verify_ini(config_file=config)
        else:
            print('ERROR: Unable To Load ini File.  Ensure bot.ini is in the CWD')
            sys.exit(1)

        self._set_ini_options(config)

        self.api_details = {'client_id': config['IMGURAPI']['ClientID'],
                            'client_secret': config['IMGURAPI']['ClientSecret'],
                            'access_token': config['IMGURAPI']['AccessToken'],
                            'refresh_token': config['IMGURAPI']['RefreshToken']}

        self.mysql_details = {'user': config['MYSQL']['User'],
                              'password': config['MYSQL']['Password'],
                              'host': config['MYSQL']['Host'],
                              'database': config['MYSQL']['Database']}

        threading.Thread(target=self.reload_ini, name='ConfigMonitor').start()

    def reload_ini(self):
        """
        Check if the config has been updated.  If it has reload it.
        """
        while True:

            if round(os.path.getmtime(self.config_file)) > self.config_last_modified:
                print('Config Changes Detected, Reloading .ini File')
                config = configparser.ConfigParser()
                config.read(self.config_file)
                self._set_ini_options(config)
                self.config_last_modified = round(os.path.getmtime(self.config_file))

            time.sleep(3)

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

        if 'HashSize' in config['OPTIONS']:
            self.hash_size = config['OPTIONS']['HashSize']

        if 'HammingCutoff' in config['OPTIONS']:
            self.hamming_cutoff = int(config['OPTIONS']['HammingCutoff'])

        if 'MinTimeBetweenRequests' in config['OPTIONS']:
            self.min_time_between_requests = int(config['OPTIONS']['MinTimeBetweenRequests'])

        if 'LogReposts' in config['OPTIONS']:
            self.log_reposts = config['OPTIONS'].getboolean('LogReposts')

        if 'Backfill' in config['OPTIONS']:
            self.backfill = config['OPTIONS'].getboolean('Backfill')

        if 'Logging' in config['OPTIONS']:
            self.logging = config['OPTIONS'].getboolean('Logging')

        if 'BackfillDepth' in config['OPTIONS']:
            self.backfill_depth = int(config['OPTIONS']['BackfillDepth'])

        if 'HashCheckProcesses' in config['OPTIONS']:
            self.hash_proc_limit = int(config['OPTIONS']['HashCheckProcesses'])

        if 'BackfillStartPage' in config['OPTIONS']:
            self.backfill_start_page = int(config['OPTIONS']['BackfillStartPage'])

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