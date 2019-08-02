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


def wait_rabbitmq(futures, internal_storage, rabbit_amqp_url=None, throw_except=True,
                  pbar=None, return_when=ALL_COMPLETED):
    """
    Wait for the Future instances `fs` to complete. Returns a 2-tuple of
    lists. The first list contains the futures that completed
    (finished or cancelled) before the wait completed. The second
    contains uncompleted futures.

    :param futures: A list of futures.
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
    if return_when != ALL_COMPLETED:
        raise NotImplementedError(return_when)

    present_jobs = {(f.executor_id, f.job_id) for f in futures}

    print(present_jobs)

    call_statuses = {}
    done_call_ids = {}

    checker_worker_queue = queue.Queue()
    for executor_id, job_id, in present_jobs:
        td = rabbitmq_checker_worker(executor_id, job_id, rabbit_amqp_url, checker_worker_queue)
        td.setDaemon(True)
        td.start()
        call_statuses[f'{executor_id}-{job_id}'] = {}
        done_call_ids[f'{executor_id}-{job_id}'] = {'total': total, 'call_ids': []}

    def call_ids_to_futures():
        fs_dones = []
        fs_notdones = []
        for f in futures:
            if f.job_id in call_statuses and f.call_id in call_statuses[f.job_id]:
                f.run_status = call_statuses[f.job_id][f.call_id]
                f.invoke_status['status_done_timestamp'] = f.run_status['status_done_timestamp']
                del f.run_status['status_done_timestamp']
                f._set_state(CallState.ready)
                fs_dones.append(f)
            else:
                fs_notdones.append(f)
        return fs_dones, fs_notdones

    def reception_finished():
        for job_id in done_call_ids:
            total = done_call_ids[job_id]['total']
            recived_call_ids = len(done_call_ids[job_id]['call_ids'])

            if total is None or total > recived_call_ids:
                return False

        return True

    while not reception_finished():
        try:
            call_status = json.loads(checker_worker_queue.get())
            call_status['status_done_timestamp'] = time.time()
        except KeyboardInterrupt:
            call_ids_to_futures()
            raise KeyboardInterrupt

        rcvd_executor_id = call_status['executor_id']
        rcvd_job_id = call_status['job_id']
        rcvd_call_id = call_status['call_id']

        if rcvd_job_id not in done_call_ids:
            done_call_ids[f'{rcvd_executor_id}-{rcvd_job_id}'] = {'total': None, 'call_ids': []}
        if rcvd_job_id not in call_statuses:
            call_statuses[f'{rcvd_executor_id}-{rcvd_job_id}'] = {}

        done_call_ids[f'{rcvd_executor_id}-{rcvd_job_id}']['call_ids'].append(rcvd_call_id)
        call_statuses[f'{rcvd_executor_id}-{rcvd_job_id}'][rcvd_call_id] = call_status

        if pbar:
            pbar.update(1)
            pbar.refresh()

        if 'new_futures' in call_status:
            new_futures = call_status['new_futures'].split('/')
            if int(new_futures[1]) != 0:
                # We received new futures to track
                executor_id_new_futures = 'TODO'
                job_id_new_futures = new_futures[0]
                total_new_futures = int(new_futures[1])
                if job_id_new_futures not in done_call_ids:
                    done_call_ids[job_id_new_futures] = {'total': total_new_futures, 'call_ids': []}
                else:
                    done_call_ids[job_id_new_futures]['total'] = total_new_futures

                if pbar:
                    pbar.total = pbar.total + total_new_futures
                    pbar.refresh()
    if pbar:
        pbar.close()

    return call_ids_to_futures()


class rabbitmq_checker_worker(threading.Thread):

    def callback(self, ch, method, properties, body):
        self.q.put(body.decode("utf-8"))

    def __init__(self, executor_id, job_id, rabbit_amqp_url, q):
        threading.Thread.__init__(self)
        self.executor_id = executor_id
        self.job_id = job_id
        self.q = q
        queue = f'{executor_id}-{job_id}'
        params = pika.URLParameters(rabbit_amqp_url)
        connection = pika.BlockingConnection(params)
        self.channel = connection.channel()  # start a channel
        self.channel.queue_declare(queue=queue, auto_delete=True)
        self.channel.basic_consume(self.callback, queue=queue, no_ack=True)

    def run(self):
        msg = ('ExecutorID {} | JobID {} - Starting consumer from rabbitmq queue'
               .format(self.executor_id, self.job_id))
        logger.debug(msg)
        self.channel.start_consuming()

    def __del__(self):
        self.channel.queue_delete(queue=self.executor_id)
        self.channel.stop_consuming()
