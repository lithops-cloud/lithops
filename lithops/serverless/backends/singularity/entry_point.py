#
# (C) Copyright Cloudlab URV 2020
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

import pika
import os
import sys
import uuid
import json
import logging
from multiprocessing import Value

from lithops.version import __version__
from lithops.utils import setup_lithops_logger, b64str_to_dict, dict_to_b64str
from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_metadata

logger = logging.getLogger('lithops.worker')


def extract_runtime_meta():
    logger.info(f"Lithops v{__version__} - Generating metadata")

    runtime_meta = get_runtime_metadata()

    channel.basic_publish(
        exchange='',
        routing_key='status_queue',
        body=json.dumps(runtime_meta),
        properties=pika.BasicProperties(
            delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
        ))
    
    logger.info(f"Runtime metadata generated")


def run_job_k8s_rabbitmq(payload, running_jobs):
    logger.info(f"Lithops v{__version__} - Starting singularity execution")

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    os.environ['__LITHOPS_BACKEND'] = 'singularity'

    function_handler(payload)
    running_jobs.value += len(payload['call_ids'])

    logger.info("Finishing singularity execution")


def manage_work_queue(ch, method, payload):
    global cpus_pod

    logger.info("Call from lithops received.")

    message = payload
    tasks = message['total_calls']

    running_jobs = Value('i', cpus_pod)  # Shared variable to track completed jobs

    # If there are more tasks than cpus in the pod, we need to send a new message
    if tasks <= running_jobs.value:
        processes_to_start = tasks
    else:
        processes_to_start = running_jobs.value

        message_to_send = message.copy()
        message_to_send['total_calls'] = tasks - running_jobs.value
        message_to_send['call_ids'] = message_to_send['call_ids'][running_jobs.value:]
        message_to_send['data_byte_ranges'] = message_to_send['data_byte_ranges'][running_jobs.value:]

        message['total_calls'] = running_jobs.value
        message['call_ids'] = message['call_ids'][:running_jobs.value]
        message['data_byte_ranges'] = message['data_byte_ranges'][:running_jobs.value]

        message_to_send = {
            'action': 'send_task',
            'payload': dict_to_b64str(message_to_send)
        }

        ch.basic_publish(
            exchange='',
            routing_key='task_queue',
            body=json.dumps(message_to_send),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
            ))

    logger.info(f"Starting {processes_to_start} processes")

    message['worker_processes'] = running_jobs.value
    running_jobs.value -= processes_to_start
    run_job_k8s_rabbitmq(message, running_jobs)

    logger.info("All processes completed")
    ch.basic_ack(delivery_tag=method.delivery_tag)


def actions_switcher(ch, method, properties, body):
    message = json.loads(body)
    action = message['action']
    encoded_payload = message['payload']

    payload = b64str_to_dict(encoded_payload)
    setup_lithops_logger(payload.get('log_level', 'INFO'))

    logger.info(f"Action {action} received from lithops.")

    if action == 'get_metadata':
        extract_runtime_meta()
        ch.basic_ack(delivery_tag=method.delivery_tag)

    elif action == 'send_task':
        manage_work_queue(ch, method, payload)

    elif action == 'stop_containers':
        ch.stop_consuming()
        ch.close()
        connection.close()
        logger.info("Stopped listening to rabbitmq")
        
        sys.exit(0)
    

if __name__ == '__main__':
    global cpus_pod

    amqp_url = sys.argv[1]
    cpus_pod = int(sys.argv[2])

    # Connect to rabbitmq
    params = pika.URLParameters(amqp_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue='task_queue', durable=True)
    channel.basic_qos(prefetch_count=1)
    
    # Start listening to the new job
    channel.basic_consume(queue='task_queue', on_message_callback=actions_switcher)

    logger.info("Listening to rabbitmq...")
    channel.start_consuming()