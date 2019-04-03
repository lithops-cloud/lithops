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

import base64
import json
import logging
import os
import signal
import subprocess
import time
import traceback
import pika
from threading import Thread
from queue import Queue
from pywren_ibm_cloud import version
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage

logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger('wrenhandler')

JOBRUNNER_PATH = "pywren_ibm_cloud/action/jobrunner.py"

PYTHON_MODULE_PATH = "/tmp/pymodules"
JOBRUNNER_CONFIG_FILENAME = "/tmp/jobrunner.config.json"
JOBRUNNER_STATS_FILENAME = "/tmp/jobrunner.stats.txt"
PYWREN_LIBS_PATH = '/action/pywren_ibm_cloud/libs'


def free_disk_space(dirname):
    """
    Returns the number of free bytes on the mount point containing DIRNAME
    """
    s = os.statvfs(dirname)
    return s.f_bsize * s.f_bavail


def b64str_to_bytes(str_data):
    str_ascii = str_data.encode('ascii')
    byte_data = base64.b64decode(str_ascii)
    return byte_data


def get_server_info():
    server_info = {'uname': subprocess.check_output("uname -a", shell=True).decode("ascii").strip(),
                   'ip_adress': subprocess.check_output("hostname -I", shell=True).decode("ascii").strip()}
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
    logger.info("Starting handler")
    response_status = {'exception': None}
    response_status['start_time'] = start_time

    context_dict = {
        'ibm_cf_request_id': os.environ.get("__OW_ACTIVATION_ID"),
        'ibm_cf_hostname': os.environ.get("HOSTNAME"),
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
    response_status['func_key'] = func_key
    response_status['data_key'] = data_key
    response_status['output_key'] = output_key
    response_status['status_key'] = status_key

    try:
        if version.__version__ != event['pywren_version']:
            raise Exception("WRONGVERSION", "PyWren version mismatch",
                            version.__version__, event['pywren_version'])

        # response_status['free_disk_bytes'] = free_disk_space("/tmp")

        custom_env = {'PYWREN_CONFIG': json.dumps(config),
                      'STORAGE_CONFIG': json.dumps(storage_config),
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

        with open(JOBRUNNER_CONFIG_FILENAME, 'w') as jobrunner_fid:
            json.dump(jobrunner_config, jobrunner_fid)

        if os.path.exists(JOBRUNNER_STATS_FILENAME):
            os.remove(JOBRUNNER_STATS_FILENAME)

        cmdstr = "python {} {}".format(JOBRUNNER_PATH, JOBRUNNER_CONFIG_FILENAME)

        logger.info("About to execute '{}'".format(cmdstr))
        setup_time = time.time()
        response_status['setup_time'] = setup_time - start_time

        """
        stdout = os.popen(cmdstr).read()
        print(stdout)
        process = subprocess.run(cmdstr, shell=True, env=local_env, bufsize=1,
                                 stdout=subprocess.PIPE, preexec_fn=os.setsid,
                                 universal_newlines=True, timeout=job_max_runtime)

        print(process.stdout)
        """
        # This is copied from http://stackoverflow.com/a/17698359/4577954
        # reasons for setting process group: http://stackoverflow.com/a/4791612
        local_env = os.environ.copy()
        process = subprocess.Popen(cmdstr, shell=True, env=local_env, bufsize=1,
                                   stdout=subprocess.PIPE, preexec_fn=os.setsid,
                                   universal_newlines=True)

        logger.info("Launched jobrunner process")

        def consume_stdout(stdout, queue):
            with stdout:
                for line in stdout:
                    print(line, end='')
                    queue.put(line)

        q = Queue()

        t = Thread(target=consume_stdout, args=(process.stdout, q))
        t.daemon = True
        t.start()
        t.join(job_max_runtime)

        response_status['exec_time'] = time.time() - setup_time

        if t.isAlive():
            # If process is still alive after t.join(job_max_runtime), kill it
            logger.error("Process exceeded maximum runtime of {} sec".format(job_max_runtime))
            # Send the signal to all the process groups
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            raise Exception("OUTATIME",  "Process executed for too long and was killed")

        if not q.empty():
            if 'Jobrunner finished' not in q.queue[q.qsize()-1].strip():
                raise Exception("OUTOFMEMORY",  "Process exceeded maximum memory and was killed")

        logger.info("Command execution finished")
        # print(subprocess.check_output("find {}".format(PYTHON_MODULE_PATH), shell=True))
        # print(subprocess.check_output("find {}".format(os.getcwd()), shell=True))

        if os.path.exists(JOBRUNNER_STATS_FILENAME):
            with open(JOBRUNNER_STATS_FILENAME, 'r') as fid:
                for l in fid.readlines():
                    key, value = l.strip().split(" ")
                    try:
                        response_status[key] = float(value)
                    except:
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
            new_futures = response_status['new_futures']
            channel.basic_publish(exchange='', routing_key=executor_id,
                                  body='{}/{}:{}:{}'.format(callgroup_id, call_id,
                                                            status,  new_futures))
            logger.info("Status sent to rabbitmq")
            connection.close()

        store_status = True
        if 'STORE_STATUS' in extra_env:
            store_status = eval(extra_env['STORE_STATUS'])

        if store_status:
            internal_storage = storage.InternalStorage(storage_config)
            internal_storage.put_data(status_key, json.dumps(response_status))
