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

import json
import logging
import os
import subprocess
import time
import traceback
import pika
import multiprocessing
from pywren_ibm_cloud import version
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.utils import sizeof_fmt
from pywren_ibm_cloud.action.jobrunner import jobrunner


logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger('handler')

PYTHON_MODULE_PATH = "/tmp/pymodules"
JOBRUNNER_STATS_FILENAME = "/tmp/jobrunner.stats.txt"
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


def ibm_cloud_function_handler(event):
    start_time = time.time()
    logger.info("Action handler started")
    response_status = {'exception': None}
    response_status['start_time'] = start_time

    context_dict = {
        'ibm_cf_request_id': os.environ.get("__OW_ACTIVATION_ID"),
        'ibm_cf_python_version': os.environ.get("PYTHON_VERSION"),
    }

    config = event['config']
    storage_config = wrenconfig.extract_storage_config(config)

    log_level = event['log_level']
    wrenlogging.ow_config(log_level)

    call_id = event['call_id']
    callgroup_id = event['callgroup_id']
    executor_id = event['executor_id']
    job_max_runtime = event.get("job_max_runtime", 590)  # default for CF
    status_key = event['status_key']
    func_key = event['func_key']
    data_key = event['data_key']
    data_byte_range = event['data_byte_range']
    output_key = event['output_key']
    extra_env = event.get('extra_env', {})

    response_status['call_id'] = call_id
    response_status['callgroup_id'] = callgroup_id
    response_status['executor_id'] = executor_id
    # response_status['func_key'] = func_key
    # response_status['data_key'] = data_key
    # response_status['output_key'] = output_key
    # response_status['status_key'] = status_key

    try:
        if version.__version__ != event['pywren_version']:
            raise Exception("WRONGVERSION", "PyWren version mismatch",
                            version.__version__, event['pywren_version'])

        # response_status['free_disk_bytes'] = free_disk_space("/tmp")

        custom_env = {'PYWREN_CONFIG': json.dumps(config),
                      'PYWREN_EXECUTOR_ID':  executor_id,
                      'PYTHONPATH': "{}:{}".format(os.getcwd(), PYWREN_LIBS_PATH),
                      'PYTHONUNBUFFERED': 'True'}

        os.environ.update(custom_env)
        os.environ.update(extra_env)

        # pass a full json blob
        jobrunner_config = {'func_key': func_key,
                            'data_key': data_key,
                            'log_level': log_level,
                            'data_byte_range': data_byte_range,
                            'python_module_path': PYTHON_MODULE_PATH,
                            'output_key': output_key,
                            'stats_filename': JOBRUNNER_STATS_FILENAME}

        if os.path.exists(JOBRUNNER_STATS_FILENAME):
            os.remove(JOBRUNNER_STATS_FILENAME)

        setup_time = time.time()
        response_status['setup_time'] = round(setup_time - start_time, 8)

        result_queue = multiprocessing.Queue()
        jr = jobrunner(jobrunner_config, result_queue)
        jr.daemon = True
        logger.info("Starting jobrunner process")
        jr.start()
        jr.join(job_max_runtime)
        response_status['exec_time'] = round(time.time() - setup_time, 8)

        if jr.is_alive():
            # If process is still alive after jr.join(job_max_runtime), kill it
            logger.error("Process exceeded maximum runtime of {} sec".format(job_max_runtime))
            # Send the signal to all the process groups
            jr.terminate()
            raise Exception("OUTATIME",  "Process executed for too long and was killed")

        try:
            # Only 1 message is returned by jobrunner
            result_queue.get(block=False)
        except Exception:
            # If no message, this means that the process was killed due memory usage
            raise Exception("OUTOFMEMORY",  "Process exceeded maximum memory and was killed")

        # print(subprocess.check_output("find {}".format(PYTHON_MODULE_PATH), shell=True))
        # print(subprocess.check_output("find {}".format(os.getcwd()), shell=True))

        if os.path.exists(JOBRUNNER_STATS_FILENAME):
            with open(JOBRUNNER_STATS_FILENAME, 'r') as fid:
                for l in fid.readlines():
                    key, value = l.strip().split(" ")
                    try:
                        response_status[key] = float(value)
                    except Exception:
                        response_status[key] = value

        response_status['host_submit_time'] = event['host_submit_time']
        # response_status['server_info'] = get_server_info()
        response_status.update(context_dict)
        response_status['end_time'] = time.time()

    except Exception as e:
        # internal runtime exceptions
        logger.error("There was an exception: {}".format(str(e)))
        response_status['end_time'] = time.time()
        response_status['exception'] = str(e)
        response_status['exception_args'] = e.args
        response_status['exception_traceback'] = traceback.format_exc()

    finally:
        rabbit_amqp_url = config['rabbitmq'].get('amqp_url')
        if rabbit_amqp_url:
            params = pika.URLParameters(rabbit_amqp_url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=executor_id, auto_delete=True)
            status = 'ok'
            if response_status['exception']:
                status = 'error'
            try:
                new_futures = response_status.get('new_futures', 'None/0')
                channel.basic_publish(exchange='', routing_key=executor_id,
                                      body='{}/{}:{}:{}'.format(callgroup_id, call_id,
                                                                status,  new_futures))
                logger.info("Status sent to rabbitmq")
            except Exception:
                logger.error("Unable to send status to rabbitmq")

            connection.close()

        store_status = True
        if 'STORE_STATUS' in extra_env:
            store_status = eval(extra_env['STORE_STATUS'])

        if store_status:
            internal_storage = storage.InternalStorage(storage_config)
            response_status = json.dumps(response_status)
            logger.info("Storing {} - Size: {}".format(status_key, sizeof_fmt(len(response_status))))
            internal_storage.put_data(status_key, response_status)
