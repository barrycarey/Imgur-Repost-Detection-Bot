import threading
from distance import hamming
from Dhash import dhash
from multiprocessing import Pool, cpu_count
import time

class HashProcessing():

    def __init__(self, config, image_ids, records):

        self.config = config
        self.hash_queue = []
        self.repost_queue = []
        self.records = records
        self.processed_ids = image_ids
        self.total_default_threads = threading.active_count() + 1
        self.active_hash_threads = 0
        self.total_in_queue = 0
        self.pool_status = 'Running'

        threading.Thread(target=self._spawn_main_hash_thread_proc, name="Main Hash Thread").start()


    def proc_cb(self, r):
        self.total_in_queue -= 1
        if r:
            self.repost_queue.append(r)

    def cb_error(self, r):
        print('Error in process: ' + r)

    def _spawn_main_hash_thread_proc(self):
        """
        Starts up a process pool using the number of processes set in the config.
        As new images are added to the hash queue they are popped off and submitted to the process pool.
        """
        while True:
            self.pool_status = 'Running'
            process_limit = self.config.hash_proc_limit
            pool = self.create_pool(process_limit)
            while True:

                if len(self.hash_queue) > 0:
                    current_hash = self.hash_queue.pop(0)
                    self.total_in_queue += 1
                    pool.apply_async(self._repost_checker_proc, args=(current_hash, self.records, self.config.hash_size,
                                                                      self.config.hamming_cutoff), callback=self.proc_cb,
                                     error_callback=self.cb_error)

                # If user changes process limit close down pool and recreate
                if process_limit != self.config.hash_proc_limit:
                    print('Process limit changed.  Closing this pool and creating new')
                    self.pool_status = 'Emptying For Process Count Change'
                    pool.close()
                    pool.join()
                    break

    @staticmethod
    def create_pool(self, process_limit):
        return Pool(processes=process_limit, maxtasksperchild=15)

    def _repost_checker_proc(self, to_be_checked, records, hashsize, hd):

        results = [{
            'image_id': to_be_checked['image_id'],
            'older_images': []
        }]

        found_repost = None

        hash_size = 'hash' + hashsize

        for r in records:

            if to_be_checked['image_id'] == r['image_id'] or r['user'] == to_be_checked['user']:
                continue

            try:
                hamming_distance = hamming(to_be_checked[hash_size], r[hash_size])
            except ValueError:
                continue

            if hamming_distance < hd:
                found_repost = True
                results[0]['older_images'].append(r)

        return results if found_repost else {}


    def generate_hash(self, img):
        """
        Generate the dhash of the provided image.
        """
        results = {}
        results['hash16'] = dhash(img, hash_size=8)
        results['hash64'] = dhash(img, hash_size=16)
        results['hash256'] = dhash(img, hash_size=32)
        return results