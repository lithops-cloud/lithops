"""
Simple Lithops example using the remote invoker.

With 'remote_invoker' enabled the client does not invoke the map()
activations itself. It spawns one cloud function that does the invoking
from inside the cloud, which pays off when a job has many activations and
the client sits on a slow link.

The feature is a backend setting rather than an API call, so nothing in
the code below is specific to it. Enable it in the config of the compute
backend:

    lithops:
        backend: aws_lambda
        storage: aws_s3

    aws_lambda:
        remote_invoker: True

The remote invoker follows the calls of this executor from the cloud, so
it is monitored as well as the client is. With a message monitoring
backend the two watch a queue each: 'lithops-<executor_id>' for the
client and 'lithops-<executor_id>-invoker' for the invoker, and every
call reports to both. Worth exercising with, since a queue is the case
where they could otherwise take each other's messages:

    lithops:
        monitoring: aws_sqs
"""
import lithops
import time

TOTAL_ACTIVATIONS = 20


def my_map_function(id, x):
    print(f"I'm activation number {id}")
    time.sleep(2)
    return x + 7


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, range(TOTAL_ACTIVATIONS))
    results = fexec.get_result()

    print(results)
    assert results == [x + 7 for x in range(TOTAL_ACTIVATIONS)]
    print(f'{TOTAL_ACTIVATIONS} activations returned the expected results')
