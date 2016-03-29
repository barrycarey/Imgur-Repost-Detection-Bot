from sqlalchemy.ext.automap import automap_base
from sqlalchemy.exc import OperationalError, InternalError
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy import create_engine, DateTime, text
import datetime
import sys
import time

class ImgurRepostDB():
    """
    Main class used for dealing with the database.  From here we deal with adding new images to the database and
    checking hashes to find reposted content
    """

    def __init__(self, db_user, db_pass, db_host, db_name):

        self.records_loaded = False

        Base = automap_base()

        engine = create_engine('mysql+pymysql://{}:{}@{}/{}'.format(db_user, db_pass, db_host, db_name))

        try:
            Base.prepare(engine, reflect=True)
        except (OperationalError, InternalError) as e:
            print('Error Connecting To Database {}'.format(e))
            sys.exit(1)

        self.imgur_reposts = Base.classes.imgur_reposts
        #self.session = Session(engine)
        self.Session = scoped_session(sessionmaker(bind=engine))

    def add_entry(self, record):
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

    def update_entry(self, image_id, sub_time):
        """
        Temp method to update values in a new column
        :param image_id:
        :return:
        """
        print('Setting Image {} To Date Of {}'.format(image_id, sub_time))
        local_session = self.Session()
        local_session.query(self.imgur_reposts).filter_by(image_id=image_id).update({"submitted_to_imgur": sub_time})
        local_session.commit()
        local_session.close()


    def build_existing_ids(self):
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
