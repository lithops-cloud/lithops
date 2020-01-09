#
# Copyright 2018 PyWren Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import sys
import time
import pika
import json
import pickle
import logging
import tempfile
import traceback
import subprocess
from threading import Thread
from multiprocessing import Process
from multiprocessing import Pipe
from distutils.util import strtobool
from pywren_ibm_cloud import version
from pywren_ibm_cloud.utils import sizeof_fmt
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.runtime.function_handler.jobrunner import JobRunner
from pywren_ibm_cloud.config import extract_storage_config, cloud_logging_config, JOBS_PREFIX
from pywren_ibm_cloud.storage.utils import create_output_key, create_status_key, create_init_key


logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger('handler')

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP, JOBS_PREFIX)
PYWREN_LIBS_PATH = '/action/pywren_ibm_cloud/libs'


def free_disk_space(dirname):
    """
    Returns the number of free bytes on the mount point containing DIRNAME
    """
    s = os.statvfs(dirname)
    return s.f_bsize * s.f_bavail


def get_server_info():
    server_info = {'container_name': subprocess.check_output("uname -n", shell=True).decode("ascii").strip(),
                   'ip_address': subprocess.check_output("hostname -I", shell=True).decode("ascii").strip(),
                   # 'mac_address': subprocess.check_output("cat /sys/class/net/eth0/address", shell=True).decode("ascii").strip(),
                   'net_speed': subprocess.check_output("cat /sys/class/net/eth0/speed | awk '{print $0 / 1000\"GbE\"}'", shell=True).decode("ascii").strip(),
                   'cores': subprocess.check_output("nproc", shell=True).decode("ascii").strip(),
                   'memory': subprocess.check_output("grep MemTotal /proc/meminfo | awk '{print $2 / 1024 / 1024\"GB\"}'", shell=True).decode("ascii").strip()}
    """
    if os.path.exists("/proc"):
        server_info.update({'/proc/cpuinfo': open("/proc/cpuinfo", 'r').read(),
                            '/proc/meminfo': open("/proc/meminfo", 'r').read(),
                            '/proc/self/cgroup': open("/proc/meminfo", 'r').read(),
                            '/proc/cgroups': open("/proc/cgroups", 'r').read()})
    """
    return server_info


def send_init_event(config, init_key, response_status):
    store_status = strtobool(os.environ.get('STORE_STATUS', 'True'))
    response_status['type'] = '__init__'
    dmpd_response_status = json.dumps(response_status)

    if store_status:
        storage_config = extract_storage_config(config)
        internal_storage = InternalStorage(storage_config)
        internal_storage.put_data(init_key, '')


def function_handler(event):
    start_time = time.time()

    log_level = event['log_level']
    cloud_logging_config(log_level)
    logger.debug("Action handler started")

    extra_env = event.get('extra_env', {})
    os.environ.update(extra_env)

    response_status = {'exception': False}
    response_status['host_submit_time'] = event['host_submit_time']
    response_status['start_time'] = start_time

    context_dict = {
        'python_version': os.environ.get("PYTHON_VERSION"),
    }

    config = event['config']

    call_id = event['call_id']
    job_id = event['job_id']
    executor_id = event['executor_id']
    exec_id = "{}/{}/{}".format(executor_id, job_id, call_id)
    logger.info("Execution ID: {}".format(exec_id))

    execution_timeout = event['execution_timeout']
    logger.debug("Set function execution timeout to {}s".format(execution_timeout))

    func_key = event['func_key']
    data_key = event['data_key']
    data_byte_range = event['data_byte_range']

    status_key = create_status_key(JOBS_PREFIX, executor_id, job_id, call_id)
    output_key = create_output_key(JOBS_PREFIX, executor_id, job_id, call_id)
    init_key = create_init_key(JOBS_PREFIX, executor_id, job_id, call_id)

    response_status['call_id'] = call_id
    response_status['job_id'] = job_id
    response_status['executor_id'] = executor_id
    response_status['activation_id'] = os.environ.get('__OW_ACTIVATION_ID')

    try:
        if version.__version__ != event['pywren_version']:
            raise Exception("WRONGVERSION", "PyWren version mismatch",
                            version.__version__, event['pywren_version'])

        #send_init_event(config, init_key, response_status.copy())

        # response_status['free_disk_bytes'] = free_disk_space("/tmp")
        custom_env = {'PYWREN_CONFIG': json.dumps(config),
                      'PYWREN_FUNCTION': 'True',
                      'PYWREN_EXECUTION_ID': exec_id,
                      'PYWREN_STORAGE_BUCKET': config['pywren']['storage_bucket'],
                      'PYTHONPATH': "{}:{}".format(os.getcwd(), PYWREN_LIBS_PATH),
                      'PYTHONUNBUFFERED': 'True'}
        os.environ.update(custom_env)

        # if os.path.exists(JOBRUNNER_STATS_BASE_DIR):
        #     shutil.rmtree(JOBRUNNER_STATS_BASE_DIR, True)
        jobrunner_stats_dir = os.path.join(STORAGE_BASE_DIR, executor_id, job_id, call_id)
        os.makedirs(jobrunner_stats_dir, exist_ok=True)
        jobrunner_stats_filename = os.path.join(jobrunner_stats_dir, 'jobrunner.stats.txt')

        jobrunner_config = {'pywren_config': config,
                            'call_id':  call_id,
                            'job_id':  job_id,
                            'executor_id':  executor_id,
                            'func_key': func_key,
                            'data_key': data_key,
                            'log_level': log_level,
                            'data_byte_range': data_byte_range,
                            'output_key': output_key,
                            'stats_filename': jobrunner_stats_filename}

        setup_time = time.time()
        response_status['setup_time'] = round(setup_time - start_time, 8)

        handler_conn, jobrunner_conn = Pipe()
        jobrunner = JobRunner(jobrunner_config, jobrunner_conn)
        logger.debug('Starting JobRunner process')
        local_execution = strtobool(os.environ.get('LOCAL_EXECUTION', 'False'))
        if local_execution:
            jrp = Thread(target=jobrunner.run)
        else:
            jrp = Process(target=jobrunner.run)
        jrp.daemon = True
        jrp.start()
        jrp.join(execution_timeout)
        logger.debug('JobRunner process finished')
        response_status['exec_time'] = round(time.time() - setup_time, 8)

        if jrp.is_alive():
            # If process is still alive after jr.join(job_max_runtime), kill it
            try:
                jrp.terminate()
            except Exception:
                # thread does not have terminate method
                pass
            msg = ('Jobrunner process exceeded maximum time of {} '
                   'seconds and was killed'.format(execution_timeout))
            raise Exception('OUTATIME',  msg)

        try:
            handler_conn.recv()
        except EOFError:
            logger.error('No completion message received from JobRunner process')
            logger.debug('Assuming memory overflow...')
            # Only 1 message is returned by jobrunner when it finishes.
            # If no message, this means that the jobrunner process was killed.
            # 99% of times the jobrunner is killed due an OOM, so we assume here an OOM.
            msg = 'Jobrunner process exceeded maximum memory and was killed'
            raise Exception('OUTOFMEMORY', msg)

        # print(subprocess.check_output("find {}".format(PYTHON_MODULE_PATH), shell=True))
        # print(subprocess.check_output("find {}".format(os.getcwd()), shell=True))

        if os.path.exists(jobrunner_stats_filename):
            with open(jobrunner_stats_filename, 'r') as fid:
                for l in fid.readlines():
                    key, value = l.strip().split(" ", 1)
                    try:
                        response_status[key] = float(value)
                    except Exception:
                        response_status[key] = value
                    if key in ['exception', 'exc_pickle_fail', 'result', 'new_futures']:
                        response_status[key] = eval(value)

        # response_status['server_info'] = get_server_info()
        response_status.update(context_dict)
        response_status['end_time'] = time.time()

    except Exception:
        # internal runtime exceptions
        print('----------------------- EXCEPTION !-----------------------', flush=True)
        traceback.print_exc(file=sys.stdout)
        print('----------------------------------------------------------', flush=True)
        response_status['end_time'] = time.time()
        response_status['exception'] = True

        pickled_exc = pickle.dumps(sys.exc_info())
        pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
        response_status['exc_info'] = str(pickled_exc)

    finally:
        store_status = strtobool(os.environ.get('STORE_STATUS', 'True'))
        response_status['type'] = '__end__'
        dmpd_response_status = json.dumps(response_status)
        drs = sizeof_fmt(len(dmpd_response_status))

        rabbitmq_monitor = config['pywren'].get('rabbitmq_monitor', False)
        if rabbitmq_monitor and store_status:
            rabbit_amqp_url = config['rabbitmq'].get('amqp_url')
            status_sent = False
            output_query_count = 0
            params = pika.URLParameters(rabbit_amqp_url)
            exchange = 'pywren-{}-{}'.format(executor_id, job_id)

            while not status_sent and output_query_count < 5:
                output_query_count = output_query_count + 1
                try:
                    connection = pika.BlockingConnection(params)
                    channel = connection.channel()
                    channel.exchange_declare(exchange=exchange, exchange_type='fanout', auto_delete=True)
                    channel.basic_publish(exchange=exchange, routing_key='',
                                          body=dmpd_response_status)
                    connection.close()
                    logger.info("Execution status sent to rabbitmq - Size: {}".format(drs))
                    status_sent = True
                except Exception as e:
                    logger.error("Unable to send status to rabbitmq")
                    logger.error(str(e))
                    logger.info('Retrying to send status to rabbitmq...')
                    time.sleep(0.2)

        if store_status:
            storage_config = extract_storage_config(config)
            internal_storage = InternalStorage(storage_config)
            logger.info("Storing execution stats - status.json - Size: {}".format(drs))
            internal_storage.put_data(status_key, dmpd_response_status)
