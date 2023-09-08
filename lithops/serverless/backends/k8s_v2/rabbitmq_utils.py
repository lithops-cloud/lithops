import yaml
import pika
import json
import os
import sys
import logging
from multiprocessing import Value,Process
from yaml.loader import SafeLoader

from lithops import config

# this module provide two main functions: 
# * get_amqp_url: to conncect to rabbitmq
# * cpu_assignation: a Daemon process to assign cpu id to the workers

logger = logging.getLogger(__name__)

def get_amqp_url():
    config_data = config.load_config()
    
    try:
        amqp_url = config_data['rabbitmq']['amqp_url']
        return amqp_url
    except:
        logger.info("This version of Kubernetes runtime requires RabbitMQ")
        raise Exception("RabbitMQ amqp_url not found in configuration")

params = pika.URLParameters(get_amqp_url())
connection = pika.BlockingConnection(params)

channel = connection.channel()

# assign ID to processes -  begin
n_processes = 0
range_begin = Value('i', 0)

channel.queue_declare(queue='id-assignation')
channel.queue_declare(queue='receive-assignation')

# function to assign id ranges
def _assign_id(ch, method, properties, body):
    global n_processes

    recep               = json.loads(body)
    num_cpus            = recep["num_cpus"]
    data_reception_id   = recep["data_reception_id"]

    msg = { 
            "range_start" : range_begin.value,
            "range_end"   : range_begin.value + num_cpus -1,
            "total_cpus"  : n_processes
          }

    range_begin.value = range_begin.value + num_cpus
    channel.basic_publish(exchange='', routing_key=data_reception_id, body=json.dumps(msg))

    if n_processes <= range_begin.value  :
        channel.stop_consuming()


channel.basic_consume(queue='id-assignation', on_message_callback=_assign_id, auto_ack=True)
# assign ID to processes -  end

def _cpu_assignation():
    try:
        channel.start_consuming()
    finally:
        try:
            logger.debug("Closing channel")
            connection.close()
            logger.debug("Exiting application")
            sys.exit(0)
        except SystemExit:
            os._exit(0)

def _start_cpu_assignation(n_procs):
    global n_processes
    n_processes = n_procs
    logger.info(f"Total cpus of the pods: {n_processes}")
    if n_processes == 0:
        raise ValueError("Total CPUs of the pods cannot be 0")
    process = Process(target=_cpu_assignation)
    process.start()

    process.join()
