import sys
import os
import uuid
import flask
import logging
import pkgutil
import multiprocessing
import time
import threading
import importlib

from lithops.version import __version__
from lithops.worker import function_invoker
from lithops.config import DOCKER_FOLDER
from lithops.config import extract_compute_config, extract_storage_config
from lithops.storage import InternalStorage
from lithops.compute.utils import get_remote_client

log_file = os.path.join(DOCKER_FOLDER, 'proxy.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG)
logger = logging.getLogger('__main__')


proxy = flask.Flask(__name__)

last_usage_time = time.time()
last_job = None
keeper = None


def budget_keeper(client, internal_storage):
    global last_usage_time
    global last_job

    logger.info("BudgetKeeper started")

    while True:
        # time since last invocation start or complete
        time_since_last_usage = time.time() - last_usage_time

        minimal_sleep_time = client.soft_dismantle_timeout / 10
        if time_since_last_usage < minimal_sleep_time:
            logger.debug("Time since last usage: {}, going to sleep for {}".format(time_since_last_usage, minimal_sleep_time))
            time.sleep(minimal_sleep_time)
            continue

        # if there is incompleted invocation, wait for completion or for hard_dismantle_timeout
        if last_job:
            callids_running_in_job, callids_done_in_job = internal_storage.get_job_status(last_job['executor_id'], last_job['job_id'])

            logger.debug("callids_running_in_job {}".format(len(callids_running_in_job)))
            if len(callids_running_in_job) > 0:
                time_to_dismantle = client.hard_dismantle_timeout - time_since_last_usage
            else:
                last_job = None
                last_usage_time = time.time()
                continue
        else:
            time_to_dismantle = client.soft_dismantle_timeout - time_since_last_usage

        logger.info("Time to dismantle: {}".format(time_to_dismantle))
        if time_to_dismantle < 0:
            # unset 'L_FUNCTION' environment variable that prevents token manager generate new token
            del os.environ['LITHOPS_FUNCTION']
            logger.info("Dismantling setup")
            try:
                client.dismantle()
            except Exception as e:
                logger.info("Dismantle error {}".format(e))
        else:
            time.sleep(minimal_sleep_time)

def _init_keeper(config):
    global keeper
    compute_config = extract_compute_config(config)
    client = get_remote_client(compute_config)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    keeper = threading.Thread(target=budget_keeper, args=(client, internal_storage, ))
    keeper.start()

@proxy.route('/', methods=['POST'])
def run():
    def error():
        response = flask.jsonify({'error': 'The action did not receive a dictionary as an argument.'})
        response.status_code = 404
        return complete(response)

    sys.stdout = open(log_file, 'w')

    global last_usage_time
    global keeper
    global last_job

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__PW_ACTIVATION_ID'] = act_id

    last_usage_time = time.time()
    last_job = message['job_description']

    if 'remote_invoker' in message:
        try:
            # init keeper only when remote_client configuration provided
            if 'remote_client' in message['config']['lithops'] and not keeper:
                _init_keeper(message['config'])

            # remove 'remote_client' configuration
            message['config']['lithops'].pop('remote_client', None)

            logger.info("Lithops v{} - Starting Docker invoker".format(__version__))
            message['config']['lithops']['remote_invoker'] = False
            message['config']['lithops']['compute_backend'] = 'localhost'

            if 'localhost' not in message['config']:
                message['config']['localhost'] = {}

            if message['config']['lithops']['workers'] is None:
                total_cpus = multiprocessing.cpu_count()
                message['config']['lithops']['workers'] = total_cpus
                message['config']['localhost']['workers'] = total_cpus
            else:
                message['config']['localhost']['workers'] = message['config']['lithops']['workers']

            message['invokers'] = 0
            message['log_level'] = None

            function_invoker(message)
        except Exception as e:
            logger.info(e)

    response = flask.jsonify({"activationId": act_id})
    response.status_code = 202

    return complete(response)


@proxy.route('/preinstalls', methods=['GET', 'POST'])
def preinstalls_task():
    logger.info("Extracting preinstalled Python modules...")

    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta['python_ver'] = str(python_version[0])+"."+str(python_version[1])
    response = flask.jsonify(runtime_meta)
    response.status_code = 200
    logger.info("Done!")

    return complete(response)


def complete(response):
    # Add sentinel to stdout/stderr
    sys.stdout.write('%s\n' % 'XXX_THE_END_OF_AN_ACTIVATION_XXX')
    sys.stdout.flush()

    return response


def main():
    port = int(os.getenv('PORT', 8080))
    proxy.run(debug=True, host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()
