"""
Simple Lithops example using rabbitmq to wait map function invocations
RabbitMQ amqp_url must be in configuration to make it working.
"""
import lithops
import time

total = 10


def my_function(x):
    time.sleep(2)
    return x + 7


if __name__ == "__main__":
    fexec = lithops.FunctionExecutor(runtime_memory=256)
    fexec.map(my_function, range(total))
    fexec.wait()  # blocks current execution until all function activations finish
    fexec.clean()

    # Activate RabbitMQ as a monitoring system
    fexec = lithops.FunctionExecutor(runtime_memory=256, monitoring='rabbitmq')
    fexec.map(my_function, range(total))
    fexec.wait()  # blocks current execution until all function activations finish
    fexec.clean()
