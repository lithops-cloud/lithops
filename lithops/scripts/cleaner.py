import os
import time
import pickle
import logging
from concurrent.futures import ThreadPoolExecutor

from lithops.storage import Storage
from lithops.storage.utils import clean_bucket
from lithops.constants import JOBS_PREFIX, TEMP_PREFIX, CLEANER_DIR,\
    CLEANER_PID_FILE, CLEANER_LOG_FILE

logger = logging.getLogger('cleaner')
logging.basicConfig(filename=CLEANER_LOG_FILE, level=logging.INFO,
                    format=('%(asctime)s [%(levelname)s] %(module)s'
                            ' - %(funcName)s: %(message)s'))


def clean():

    def clean_file(file_name):
        file_location = os.path.join(CLEANER_DIR, file_name)

        if file_location in [CLEANER_LOG_FILE, CLEANER_PID_FILE]:
            return

        with open(file_location, 'rb') as pk:
            data = pickle.load(pk)

        if 'jobs_to_clean' in data:
            jobs_to_clean = data['jobs_to_clean']
            storage_config = data['storage_config']
            clean_cloudobjects = data['clean_cloudobjects']
            storage = Storage(storage_config=storage_config)

            for job_key in jobs_to_clean:
                logger.info('Going to clean: {}'.format(job_key))

                prefix = '/'.join([JOBS_PREFIX, job_key])
                clean_bucket(storage, storage.bucket, prefix)

                if clean_cloudobjects:
                    prefix = '/'.join([TEMP_PREFIX, job_key])
                    clean_bucket(storage, storage.bucket, prefix)

        if 'cos_to_clean' in data:
            logger.info('Going to clean cloudobjects')
            cos_to_clean = data['cos_to_clean']
            storage_config = data['storage_config']
            storage = Storage(storage_config=storage_config)

            for co in cos_to_clean:
                if co.backend == storage.backend:
                    logging.info('Cleaning {}://{}/{}'.format(co.backend,
                                                              co.bucket,
                                                              co.key))
                    storage.delete_object(co.bucket, co.key)

        if os.path.exists(file_location):
            os.remove(file_location)

    while True:
        files_to_clean = os.listdir(CLEANER_DIR)
        if len(files_to_clean) <= 2:
            break
        with ThreadPoolExecutor(max_workers=32) as ex:
            ex.map(clean_file, files_to_clean)
        time.sleep(5)


if __name__ == '__main__':
    if not os.path.isfile(CLEANER_PID_FILE):
        logger.info("Starting Job and Cloudobject Cleaner")
        with open(CLEANER_PID_FILE, 'w') as cf:
            cf.write(str(os.getpid()))
        try:
            clean()
        except Exception as e:
            raise e
        finally:
            os.remove(CLEANER_PID_FILE)
        logger.info("Job and Cloudobject Cleaner finished")
