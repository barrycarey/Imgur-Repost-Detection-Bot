from sqlalchemy.ext.automap import automap_base
from sqlalchemy.exc import OperationalError, InternalError
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy import create_engine, DateTime, text
import datetime
import sys

class ImgurRepostDB():
    """
    Main class used for dealing with the database.  From here we deal with adding new images to the database and
    checking hashes to find reposted content
    """

    def __init__(self, db_user, db_pass, db_host, db_name):

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


    def add_entry(self, url, hash, user, image_id):
        """
        Insert the provided data into the database
        :param url: image URL
        :param hash: hash of the current image
        :param user: Imgur user that posted the image
        :param image_id: the Imgur ID of the image
        """

        local_session = self.Session()  # Grab the DB session for this thread

        print('Inserting {}'.format(url))
        local_session.add(self.imgur_reposts(date=datetime.datetime.utcnow(), url=url, hash=hash, user=user, image_id=image_id))
        local_session.flush()
        local_session.commit()

    def check_repost(self, hash_to_check, image_id, user):
        """
        Check if the provided image is a repost by calculating the hamming distance between provided hash and all hashes
        in the database.
        """
        results = []
        local_session = self.Session()  # Grab the DB session for this thread

        if hash_to_check == '0000000000000000':
            return results, 0

        # TODO This is pretty dirty.
        result = local_session.query(self.imgur_reposts).from_statement(text("SELECT id, date, image_id, url, hash, user, BIT_COUNT( CAST(CONV(hash, 16, 10) AS UNSIGNED) ^ CAST(CONV(:testhash, 16, 10) AS UNSIGNED)) AS hamming_distance FROM imgur_reposts HAVING hamming_distance < 2 ORDER BY date ASC")).params(testhash=hash_to_check).all()

        if len(result) > 0:
            for row in result:
                if not row.image_id == image_id and not row.user == user:
                    results.append(row)

        # TODO Don't think we need to return the length of result here.
        return results, len(result)

    def build_existing_ids(self):
        """
        Build a list of all existing Image IDs in the database.  The prevents us from reinserting an image we have already
        checked.
        """

        print('Loading Records From The Database.  This May Take Several Minutes.')
        local_session = self.Session()  # Grab the DB session for this thread

        # TODO We can probably limit this to last 24 hours of IDs.
        existing_records = []
        result = local_session.query(self.imgur_reposts).all()
        if len(result) > 0:
            for r in result:
                existing_records.append(r.image_id)

        print('Loaded {} Records From Database'.format(len(existing_records)))
        return existing_records