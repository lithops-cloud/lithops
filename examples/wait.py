"""
Simple PyWren example using rabbitmq to wait map function invocations
RabbitMQ amqp_url must be in configuration to make it working.
"""
import lithops
import time

total = 10


def my_function(x):
    time.sleep(2)
    return x + 7


if __name__ == "__main__":
    pw = lithops.ibm_cf_executor(runtime_memory=256)
    pw.map(my_function, range(total))
    pw.wait()  # blocks current execution until all function activations finish
    pw.clean()

    # Activate RabbitMQ as a monitoring system
    pw = lithops.ibm_cf_executor(runtime_memory=256, rabbitmq_monitor=True)
    pw.map(my_function, range(total))
    pw.wait()  # blocks current execution until all function activations finish
    pw.clean()
