import json
import time
import pika
import queue
import logging
import threading
from pywren_ibm_cloud.future import CallState

logger = logging.getLogger(__name__)
logging.getLogger('pika').setLevel(logging.WARNING)

ALL_COMPLETED = 1
ANY_COMPLETED = 2
ALWAYS = 3


def wait_rabbitmq(fs, internal_storage, rabbit_amqp_url=None, throw_except=True,
                  pbar=None, return_when=ALL_COMPLETED):
    """
    Wait for the Future instances `fs` to complete. Returns a 2-tuple of
    lists. The first list contains the futures that completed
    (finished or cancelled) before the wait completed. The second
    contains uncompleted futures.

    :param fs: A list of futures.
    :param executor_id: executor's ID.
    :param internal_storage: Storage handler to poll cloud storage.
    :param rabbit_amqp_url: amqp url for accessing rabbitmq.
    :param pbar: Progress bar.
    :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
    :return: `(fs_dones, fs_notdones)`
        where `fs_dones` is a list of futures that have completed
        and `fs_notdones` is a list of futures that have not completed.
    :rtype: 2-tuple of lists
    """
    # FIXME:  this will eventually provide an optimization for checking if a large
    # number of futures have completed without too much network traffic
    # by exploiting the callset

    N = len(fs)
    # These are performance-related settings that we may eventually
    # want to expose to end users:
    MAX_DIRECT_QUERY_N = 64
    RETURN_EARLY_N = 32
    RANDOM_QUERY = False

    if return_when == ALL_COMPLETED:

        job_id = fs[0].job_id
        executor_id = fs[0].executor_id
        return _wait_rabbitmq(fs, executor_id, job_id, rabbit_amqp_url, pbar, N)

        result_count = 0

        while result_count < N:
            fs_dones, fs_notdones = _wait_storage(fs, executor_id,
                                                  internal_storage,
                                                  download_results,
                                                  throw_except,
                                                  RETURN_EARLY_N,
                                                  MAX_DIRECT_QUERY_N,
                                                  random_query=RANDOM_QUERY,
                                                  THREADPOOL_SIZE=THREADPOOL_SIZE,
                                                  pbar=pbar)
            N = len(fs)
            if pbar and pbar.total != N:
                pbar.total = N
                pbar.refresh()

            result_count = len(fs_dones)
            if result_count == N:
                return fs_dones, fs_notdones

    elif return_when == ANY_COMPLETED:
        while True:
            fs_dones, fs_notdones = _wait_storage(fs, executor_id,
                                                  internal_storage,
                                                  download_results,
                                                  throw_except,
                                                  RETURN_EARLY_N,
                                                  MAX_DIRECT_QUERY_N,
                                                  random_query=RANDOM_QUERY,
                                                  THREADPOOL_SIZE=THREADPOOL_SIZE)

            if len(fs_dones) != 0:
                return fs_dones, fs_notdones
            else:
                time.sleep(WAIT_DUR_SEC)

    elif return_when == ALWAYS:
        return _wait_storage(fs, executor_id,
                             internal_storage,
                             download_results,
                             throw_except,
                             RETURN_EARLY_N,
                             MAX_DIRECT_QUERY_N,
                             random_query=RANDOM_QUERY,
                             THREADPOOL_SIZE=THREADPOOL_SIZE)
    else:
        raise ValueError()


class rabbitmq_checker_worker(threading.Thread):

    def callback(self, ch, method, properties, body):
        self.q.put(body.decode("utf-8"))

    def __init__(self, executor_id, rabbit_amqp_url, q):
        threading.Thread.__init__(self)
        self.executor_id = executor_id
        self.q = q
        params = pika.URLParameters(rabbit_amqp_url)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()  # start a channel
        self.channel.queue_declare(queue=self.executor_id, auto_delete=True)
        self.channel.basic_consume(self.callback, queue=self.executor_id, no_ack=True)

    def run(self):
        msg = 'ExecutorID {} - Starting consumer from rabbitmq queue'.format(self.executor_id)
        logger.debug(msg)
        self.channel.start_consuming()

    def __del__(self):
        self.channel.queue_delete(queue=self.executor_id)
        self.channel.stop_consuming()


def _wait_rabbitmq(fs, executor_id, job_id, rabbit_amqp_url, pbar, total):
    q = queue.Queue()
    td = rabbitmq_checker_worker(executor_id, rabbit_amqp_url, q)
    td.setDaemon(True)
    td.start()

    task_statuses = {}
    task_statuses[job_id] = {}
    done_task_ids = {}
    done_task_ids[job_id] = {'total': total, 'task_ids': []}

    def call_ids_to_futures():
        fs_dones = []
        fs_notdones = []
        for f in fs:
            if f.job_id in task_statuses and f.call_id in task_statuses[f.job_id]:
                f.run_status = task_statuses[f.job_id][f.call_id]
                f.invoke_status['status_done_timestamp'] = f.run_status['status_done_timestamp']
                del f.run_status['status_done_timestamp']
                f._set_state(CallState.ready)
                fs_dones.append(f)
            else:
                fs_notdones.append(f)
        return fs_dones, fs_notdones

    def reception_finished():
        for cg_id in done_task_ids:
            total = done_task_ids[cg_id]['total']
            recived_call_ids = len(done_task_ids[cg_id]['task_ids'])

            if total is None or total > recived_call_ids:
                return False

        return True

    while not reception_finished():
        try:
            call_status = json.loads(q.get())
            call_status['status_done_timestamp'] = time.time()
        except KeyboardInterrupt:
            call_ids_to_futures()
            raise KeyboardInterrupt

        rcvd_job_id = call_status['job_id']
        rcvd_task_id = call_status['call_id']

        if rcvd_job_id not in done_task_ids:
            done_task_ids[rcvd_job_id] = {'total': None, 'task_ids': []}
        if rcvd_job_id not in task_statuses:
            task_statuses[rcvd_job_id] = {}

        done_task_ids[rcvd_job_id]['task_ids'].append(rcvd_task_id)
        task_statuses[rcvd_job_id][rcvd_task_id] = call_status

        if pbar:
            pbar.update(1)
            pbar.refresh()

        if 'new_futures' in call_status:
            new_futures = call_status['new_futures'].split('/')
            if int(new_futures[1]) != 0:
                # We received new futures to track
                job_id_new_futures = new_futures[0]
                total_new_futures = int(new_futures[1])
                if job_id_new_futures not in done_task_ids:
                    done_task_ids[job_id_new_futures] = {'total': total_new_futures, 'task_ids': []}
                else:
                    done_task_ids[job_id_new_futures]['total'] = total_new_futures

                if pbar:
                    pbar.total = pbar.total + total_new_futures
                    pbar.refresh()
    if pbar:
        pbar.close()

    return call_ids_to_futures()
