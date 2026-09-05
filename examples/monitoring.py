"""
Simple Lithops example showing how the client learns that the functions
have finished, which is what wait() and get_result() rely on.

By default Lithops polls the storage backend: every function writes its
status there, and the client lists those files every couple of seconds.
That needs nothing extra, but a job with many functions means many
requests against the storage.

Instead, the status can travel through a message service, which reaches
the client as soon as each function reports. Pick one with the
'monitoring' parameter, or with 'monitoring' in the lithops section of
the config:

    storage      the default, no extra service needed
    rabbitmq     needs an 'amqp_url' in the rabbitmq section
    redis        needs a 'host' in the redis section
    aws_sqs      uses the aws section
    gcp_pubsub   uses the gcp section
    azure_queue  uses the azure_storage section

The message service has to be reachable from the client *and* from the
functions. A broker on your laptop works for localhost runs, but a
function in the cloud cannot connect back to it, so a cloud run needs a
broker both sides can see.

Run this example with the backend you have configured, for instance:

    lithops:
        monitoring: redis

    redis:
        host: 127.0.0.1
"""
import lithops
import time

TOTAL = 10

# Whichever message service your config has ready
MESSAGE_BACKEND = 'redis'


def my_function(x):
    time.sleep(2)
    return x + 7


def run(monitoring):
    print(f'--- monitoring={monitoring}')
    start = time.time()
    with lithops.FunctionExecutor(monitoring=monitoring) as fexec:
        fexec.map(my_function, range(TOTAL))
        results = fexec.get_result()
    assert results == [x + 7 for x in range(TOTAL)]
    print(f'    {TOTAL} functions done in {time.time() - start:.1f}s')


if __name__ == '__main__':
    # The default: the client polls the storage backend
    run('storage')

    # The same job, with the statuses pushed through a message service
    run(MESSAGE_BACKEND)
