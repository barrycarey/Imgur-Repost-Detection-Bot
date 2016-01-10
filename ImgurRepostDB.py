from sqlalchemy.ext.automap import automap_base
from sqlalchemy.exc import OperationalError, InternalError
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, DateTime, text
import datetime
import sys

class ImgurRepostDB():

    def __init__(self, db_user, db_pass, db_host, db_name):

        Base = automap_base()

        engine = create_engine('mysql+pymysql://{}:{}@{}/{}'.format(db_user, db_pass, db_host, db_name))

        try:
            Base.prepare(engine, reflect=True)
        except (OperationalError, InternalError) as e:
            print('Error Connecting To Database {}'.format(e))
            sys.exit(1)

        self.imgur_reposts = Base.classes.imgur_reposts
        self.session = Session(engine)

    def add_entry(self, url, hash, user, image_id):
        """
        Insert the provided data into the database
        :param url: image URL
        :param hash: hash of the current image
        :param user: Imgur user that posted the image
        :param image_id: the Imgur ID of the image
        """
        print('Inserting {}'.format(url))
        self.session.add(self.imgur_reposts(date=datetime.datetime.utcnow(), url=url, hash=hash, user=user, image_id=image_id))
        self.session.flush()
        self.session.commit()

    def check_repost(self, hash_to_check, image_id, user):
        """
        Check if the provided image is a repost by calculating the hamming distance between provided hash and all hashes
        in the database.
        """
        results = []

        if hash_to_check == '0000000000000000':
            return results, 0

        # TODO This is pretty dirty.
        result = self.session.query(self.imgur_reposts).from_statement(text("SELECT id, date, image_id, url, hash, user, BIT_COUNT( CAST(CONV(hash, 16, 10) AS UNSIGNED) ^ CAST(CONV(:testhash, 16, 10) AS UNSIGNED)) AS hamming_distance FROM imgur_reposts HAVING hamming_distance < 2 ORDER BY date ASC")).params(testhash=hash_to_check).all()

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
        # TODO We can probably limit this to last 24 hours of IDs.
        existing_records = []
        result = self.session.query(self.imgur_reposts).all()
        if len(result) > 0:
            for r in result:
                existing_records.append(r.image_id)

        print('Loaded {} Records From Database'.format(len(existing_records)))
        return existing_records