"""
Simple Lithops example using 2 function invocations (writer, reader) with
the 'rabbitmq' parameter, which is a pika.BlockingConnection() instance.
RabbitMQ amqp_url must be in configuration to make it working.
"""
import lithops


def my_function_writer(queue_name, message, rabbitmq):
    channel = rabbitmq.channel()
    channel.queue_declare(queue=queue_name, auto_delete=True)
    channel.basic_publish(exchange='', routing_key=queue_name, body=message)
    rabbitmq.close()


def my_function_reader(queue_name, rabbitmq):
    message = None

    def callback(ch, method, properties, body):
        ch.stop_consuming()
        nonlocal message
        message = body.decode('utf-8')
        print(f'Received message: {message}')

    channel = rabbitmq.channel()
    channel.queue_declare(queue=queue_name, auto_delete=True)  # No effect if the queue already exists
    channel.basic_consume(callback, queue=queue_name, no_ack=True)
    channel.start_consuming()
    rabbitmq.close()

    return message


if __name__ == '__main__':
    queue_name = 'my_queue'
    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function_writer, (queue_name, 'This is a rabbitmq test'))

    fexec = lithops.FunctionExecutor()
    fexec.call_async(my_function_reader, queue_name)
    print(fexec.get_result())
