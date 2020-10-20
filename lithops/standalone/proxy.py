import os
import uuid
import flask
import logging
import time
import threading
import json

from lithops.config import STORAGE_DIR, JOBS_DONE_DIR, \
    REMOTE_INSTALL_DIR
from lithops.localhost.localhost import LocalhostHandler
from lithops.standalone.standalone import StandaloneHandler


os.makedirs(STORAGE_DIR, exist_ok=True)
log_file = os.path.join(STORAGE_DIR, 'proxy.log')
logging.basicConfig(filename=log_file, level=logging.INFO)
logger = logging.getLogger('proxy')
KEEPER_CHECK_INTERVAL = 30

proxy = flask.Flask(__name__)

last_usage_time = time.time()
keeper = None
jobs = {}


def budget_keeper(handler, ):
    global last_usage_time
    global jobs

    logger.info("BudgetKeeper started")

    while True:
        time_since_last_usage = time.time() - last_usage_time

        for job in jobs.keys():
            if os.path.isfile('{}/{}.done'.format(JOBS_DONE_DIR, job)):
                jobs[job] = 'done'

        if len(jobs) > 0 and all(value == 'done' for value in jobs.values()):
            time_to_dismantle = int(handler.soft_dismantle_timeout - time_since_last_usage)
        else:
            time_to_dismantle = int(handler.hard_dismantle_timeout - time_since_last_usage)

        if time_to_dismantle > 0:
            logger.info("Time to dismantle: {} seconds".format(time_to_dismantle))
            time.sleep(KEEPER_CHECK_INTERVAL)
        else:
            logger.info("Dismantling setup")
            try:
                handler.backend.stop()
            except Exception as e:
                logger.info("Dismantle error {}".format(e))


def init_keeper():
    global keeper

    config_file = os.path.join(REMOTE_INSTALL_DIR, 'config')
    with open(config_file, 'r') as cf:
        serverfull_config = json.load(cf)
    handler = StandaloneHandler(serverfull_config)

    if handler.auto_dismantle:
        keeper = threading.Thread(target=budget_keeper, args=(handler,))
        keeper.daemon = True
        keeper.start()


def error():
    response = flask.jsonify({'error': 'The action did not receive a dictionary as an argument.'})
    response.status_code = 404
    return response


@proxy.route('/run', methods=['POST'])
def run():
    """
    Run a job
    """
    global last_usage_time
    global jobs

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error()

    last_usage_time = time.time()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    runtime = message['job_description']['runtime_name']
    logger.info("Running job in {}".format(runtime))

    executor_id = message['job_description']['executor_id']
    job_id = message['job_description']['job_id']
    jobs['{}_{}'.format(executor_id.replace('/', '-'), job_id)] = 'running'

    localhost_handler = LocalhostHandler({'runtime': runtime})
    localhost_handler.run_job(message)

    response = flask.jsonify({'activationId': act_id})
    response.status_code = 202

    return response


@proxy.route('/ping', methods=['GET'])
def ping():
    response = flask.jsonify({'response': 'pong'})
    response.status_code = 200

    return response


@proxy.route('/preinstalls', methods=['GET'])
def preinstalls():

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error()

    runtime = message['runtime']
    logger.info("Extracting preinstalled Python modules from {}".format(runtime))
    localhost_handler = LocalhostHandler(message)
    runtime_meta = localhost_handler.create_runtime(runtime)
    response = flask.jsonify(runtime_meta)
    response.status_code = 200

    return response


def main():
    init_keeper()
    port = int(os.getenv('PORT', 8080))
    proxy.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)


if __name__ == '__main__':
    main()
