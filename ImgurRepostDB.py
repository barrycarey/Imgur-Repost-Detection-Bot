from sqlalchemy.ext.automap import automap_base
from sqlalchemy.exc import OperationalError, InternalError
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy import create_engine, DateTime, text
import datetime
import sys
import time
from pymongo import MongoClient

class ImgurRepostDB():
    """
    Main class used for dealing with the database.  From here we deal with adding new images to the database and
    checking hashes to find reposted content
    """

    def __init__(self, config):

        self.records_loaded = False
        self.config = config  # TODO might be better to skip not set as instance variable
        self.storage_engine = config.database_details['storage']

        if self.storage_engine == 'mysql':
            self._setup_mysql()
        elif self.storage_engine == 'mongodb':
            self._setup_mongodb()



    def _setup_mysql(self):

        Base = automap_base()

        engine = create_engine('mysql+pymysql://{}:{}@{}/{}'.format(self.config.database_details['User'],
                                                                    self.config.database_details['Password'],
                                                                    self.config.database_details['Host'],
                                                                    self.config.database_details['Database']))

        try:
            Base.prepare(engine, reflect=True)
        except (OperationalError, InternalError) as e:
            print('[!] ERROR: Problem Connecting To Database {}'.format(e))
            sys.exit(1)

        self.imgur_reposts = Base.classes.imgur_reposts
        self.Session = scoped_session(sessionmaker(bind=engine))

    def _setup_mongodb(self):

        self.mongodb_client = MongoClient()
        self.mongodb_db = self.mongodb_client[self.config.database_details['Database']]


    def add_entry(self, record):
        """
        Forward add requests to correct mathod for storage engine
        :param record:
        :return:
        """
        if self.storage_engine == 'mysql':
            self._add_entry_mysql(record)
        elif self.storage_engine == 'mongodb':
            self._add_entry_mongodb(record)


    def _add_entry_mongodb(self, record):
        record['date'] = datetime.datetime.utcnow()
        result = self.mongodb_db[self.config.database_details['Collection']].insert_one(record)

    def _add_entry_mysql(self, record):
        """
        Insert the provided data into the database
        """
        hash16, hash64, hash256 = 'NULL', 'NULL', 'NULL'

        if record['hash16'] != 'NULL':
            hash16 = record['hash16']

        if record['hash64'] != 'NULL':
            hash64 = record['hash64']

        if record['hash256'] != 'NULL':
            hash256 = record['hash256']

        local_session = self.Session()  # Grab the DB session for this thread

        try:
            local_session.add(self.imgur_reposts(date=datetime.datetime.utcnow(), url=record['url'], hash=hash16, hash64=hash64,
                                                 hash256=hash256, user=record['user'], image_id=record['image_id'], submitted_to_imgur=record['submitted']))
            local_session.flush()
            local_session.commit()
        except Exception as e:
            print('Exception during insert')
            print(e)

    def build_existing_ids(self):
        if self.storage_engine == 'mysql':
            return self._build_existing_ids_mysql()
        elif self.storage_engine == 'mongodb':
            return self._build_existing_ids_mongodb()

    def _build_existing_ids_mongodb(self):
        existing_records = []
        image_ids = []
        result = self.mongodb_db[self.config.database_details['Collection']].find()

        for r in result:
            image_ids.append(r['image_id'])
            record = {
                'image_id': r['image_id'],
                'url': r['url'],
                'gallery_url': 'https://imgur.com/gallery/{}'.format(r['image_id']),
                'user': r['user'],
                'submitted': r['submitted_to_imgur'],
                'hash16': r['hash16'],
                'hash64': r['hash64'],
                'hash256': r['hash256']
            }
            existing_records.append(record)

        print('Loaded {} Records From Database'.format(len(existing_records)))
        self.records_loaded = True
        return existing_records, image_ids

    def _build_existing_ids_mysql(self):
        """
        Build a list of all existing Image IDs in the database.  The prevents us from reinserting an image we have already
        checked.
        """

        print('Loading Records From The Database.  This May Take Several Minutes.')
        local_session = self.Session()  # Grab the DB session for this thread

        # TODO We can probably limit this to last 24 hours of IDs.
        existing_records = []
        #result = local_session.query(self.imgur_reposts).all()
        result = local_session.query(self.imgur_reposts).from_statement(text("SELECT * from imgur_reposts")).all()

        image_ids = []
        if len(result) > 0:
            for r in result:
                image_ids.append(r.image_id)
                record = {
                    'image_id': r.image_id,
                    'url': r.url,
                    'gallery_url': 'https://imgur.com/gallery/{}'.format(r.image_id),
                    'user': r.user,
                    'submitted': r.submitted_to_imgur,
                    'hash16': r.hash,
                    'hash64': r.hash64,
                    'hash256': r.hash256
                }
                existing_records.append(record)

        print('Loaded {} Records From Database'.format(len(existing_records)))
        self.records_loaded = True
        return existing_records, image_ids
