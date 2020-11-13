import sys
import json
import time
import pika
import queue
import pickle
import logging
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, wait
from lithops.storage.utils import create_job_key

logger = logging.getLogger(__name__)
logging.getLogger('pika').setLevel(logging.WARNING)

ALL_COMPLETED = 1
ANY_COMPLETED = 2
ALWAYS = 3


def wait_rabbitmq(fs, internal_storage, rabbit_amqp_url, download_results=False,
                  throw_except=True, pbar=None, return_when=ALL_COMPLETED, THREADPOOL_SIZE=128):
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

    thread_pool = ThreadPoolExecutor(max_workers=THREADPOOL_SIZE)
    present_jobs = {}
    done_call_ids = {}

    for f in fs:
        if (download_results and not f.done) or (not download_results and not (f.ready or f.done)):
            job_key = create_job_key(f.executor_id, f.job_id)
            if job_key not in present_jobs:
                present_jobs[job_key] = {}
            present_jobs[job_key][f.call_id] = f

    job_monitor_q = queue.Queue()
    for job_key in present_jobs.keys():
        total_calls = len(present_jobs[job_key])
        done_call_ids[job_key] = {'total': total_calls, 'call_ids': []}
        job_monitor = Thread(target=_job_monitor_thread, args=(job_key, total_calls, rabbit_amqp_url, job_monitor_q))
        job_monitor.daemon = True
        job_monitor.start()

    # thread to check possible function activations unexpected errors.
    # It will raise a Timeout error if the status is not received after X seconds.
    running_futures = []
    ftc = Thread(target=_future_timeout_checker_thread, args=(running_futures, job_monitor_q, throw_except))
    ftc.daemon = True
    ftc.start()

    def reception_finished():
        """
        Method to check if the call_status from all the function activations
        have been received.
        """
        for job_id in done_call_ids:
            total = done_call_ids[job_id]['total']
            recived_call_ids = len(done_call_ids[job_id]['call_ids'])

            if total is None or total > recived_call_ids:
                return False

        return True

    get_result_futures = []

    def get_result(f):
        f.result(throw_except=throw_except, internal_storage=internal_storage)

    while not reception_finished():
        try:
            call_status = job_monitor_q.get()
        except KeyboardInterrupt:
            raise KeyboardInterrupt

        rcvd_executor_id = call_status['executor_id']
        rcvd_job_id = call_status['job_id']
        rcvd_call_id = call_status['call_id']
        job_key = create_job_key(rcvd_executor_id, rcvd_job_id)
        fut = present_jobs[job_key][rcvd_call_id]
        fut._call_status = call_status
        fut.status(throw_except=throw_except, internal_storage=internal_storage)

        if call_status['type'] == '__init__':
            running_futures.append(fut)

        if call_status['type'] == '__end__':
            done_call_ids[job_key]['call_ids'].append(rcvd_call_id)

            if pbar:
                pbar.update(1)
                pbar.refresh()

            if 'new_futures' in call_status:
                new_futures = fut.result()
                fs.extend(new_futures)

                if pbar:
                    pbar.total = pbar.total + len(new_futures)
                    pbar.refresh()

                present_jobs_new_futures = {create_job_key(f.executor_id, f.job_id) for f in new_futures}

                for f in new_futures:
                    job_key_new_futures = create_job_key(f.executor_id, f.job_id)
                    if job_key_new_futures not in present_jobs:
                        present_jobs[job_key_new_futures] = {}
                    present_jobs[job_key_new_futures][f.call_id] = f

                for job_key_new_futures in present_jobs_new_futures:
                    total_calls = len(present_jobs[job_key_new_futures])
                    done_call_ids[job_key_new_futures] = {'total': total_calls, 'call_ids': []}
                    job_monitor = Thread(target=_job_monitor_thread, args=(job_key, total_calls, rabbit_amqp_url, job_monitor_q))
                    job_monitor.daemon = True
                    job_monitor.start()

            if 'new_futures' not in call_status and download_results:
                gr_ft = thread_pool.submit(get_result, fut)
                get_result_futures.append(gr_ft)

    wait(get_result_futures)

    return fs, []


def _job_monitor_thread(job_key, total_calls, rabbit_amqp_url, job_monitor_q):
    exchange = 'lithops-{}'.format(job_key)
    queue_0 = '{}-0'.format(exchange)
    total_calls_rcvd = 0

    def callback(ch, method, properties, body):
        nonlocal total_calls_rcvd
        call_status = json.loads(body.decode("utf-8"))
        job_monitor_q.put(call_status)
        if call_status['type'] == '__end__':
            total_calls_rcvd += 1
        if total_calls_rcvd == total_calls:
            ch.stop_consuming()

    executor_id, job_id = job_key.rsplit('-', 1)
    logger.debug('ExecutorID {} | JobID {} - Consuming from RabbitMQ '
                 'queue'.format(executor_id, job_id))
    params = pika.URLParameters(rabbit_amqp_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.basic_consume(callback, queue=queue_0, no_ack=True)
    channel.start_consuming()


def _future_timeout_checker_thread(running_futures, job_monitor_q, throw_except):
    should_run = True
    while should_run:
        try:
            while True:
                current_time = time.time()
                for fut in running_futures:
                    if fut.running:
                        fut_timeout = fut._call_status['worker_start_tstamp'] + fut.execution_timeout + 5
                        if current_time > fut_timeout:
                            msg = 'The function did not run as expected.'
                            raise TimeoutError('HANDLER', msg)
                time.sleep(5)
        except Exception:
            # generate fake TimeoutError call status
            pickled_exception = str(pickle.dumps(sys.exc_info()))
            call_status = {'type': '__end__',
                           'exception': True,
                           'exc_info': pickled_exception,
                           'executor_id': fut.executor_id,
                           'job_id': fut.job_id,
                           'call_id': fut.call_id,
                           'activation_id': fut.activation_id}
            job_monitor_q.put(call_status)
            if throw_except:
                should_run = False
