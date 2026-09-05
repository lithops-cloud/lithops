import lithops
import os
import time
import pickle


def simple_map_function(x, y):
    return x + y


def concat(lst):
    return " ".join(lst)


def hello_world(param):
    return "Hello World!"


def lithops_inside_lithops_map_function(x):
    def _func(x):
        return x

    fexec = lithops.FunctionExecutor()
    fexec.map(_func, range(x))
    return fexec.get_result()


def _started(fut):
    """
    Tells whether a future has at least started, the way the job monitor
    does. The states are mutually exclusive, so a future that already ran
    past Ready into Success or Done is no longer `ready`: testing only
    `running or ready` misses it and loops for ever
    """
    return fut.running or fut.ready or fut.success or fut.done


def _wait_until_started(futures, timeout=60):
    """
    Waits for every future to have started, so that the parent executor
    can pick them up once this one returns them. Required for the
    localhost tests to pass on Windows
    """
    deadline = time.time() + timeout
    while not all(_started(f) for f in futures):
        if time.time() > deadline:
            raise TimeoutError(
                'Nested futures did not start within '
                f'{timeout}s: {[f._state for f in futures]}'
            )
        time.sleep(0.1)


def lithops_return_futures_map(x):
    def _func(x):
        return x + 1

    fexec = lithops.FunctionExecutor()
    futures = fexec.map(_func, range(x))

    _wait_until_started(futures)

    return futures


def lithops_return_futures_map_over_partial(x):
    from functools import partial

    def _func(x, y):
        return x * y

    fexec = lithops.FunctionExecutor()
    futures = fexec.map(partial(_func, 2), range(x))

    _wait_until_started(futures)

    return futures


def lithops_return_futures_call_async(x):
    def _func(x):
        return x + 1

    fexec = lithops.FunctionExecutor()
    fut = fexec.call_async(_func, x + 5)

    _wait_until_started([fut])

    return fut


def lithops_return_futures_map_multiple(x):
    def _func(x):
        return x + 1

    fexec = lithops.FunctionExecutor()
    fut1 = fexec.map(_func, range(x))
    fut2 = fexec.map(_func, range(x))

    _wait_until_started(fut1 + fut2)

    return fut1 + fut2


def my_map_function_obj(obj, id):
    """returns a dictionary of {word:number of appearances} key:value items."""
    print('Function id: {}'.format(id))
    print('Bucket: {}'.format(obj.bucket))
    print('Key: {}'.format(obj.key))
    print('Partition num: {}'.format(obj.part))

    print('Chunk size: {}'.format(obj.chunk_size))
    print('Byte range: {}'.format(obj.data_byte_range))

    counter = {}
    data = obj.data_stream.read()

    # chunk = obj.data_stream.read(10000)
    # data = b""
    # while chunk:
    #     data += chunk
    #     chunk = obj.data_stream.read(10000)

    print('Data lenght: {}'.format(len(data)))

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1
    print('Testing map_reduce() over a bucket')
    return counter


def my_map_function_url(id, obj):
    print('I am processing the object from {}'.format(obj.url))
    print('Function id: {}'.format(id))
    print('Partition num: {}'.format(obj.part))
    print('Chunk size: {}'.format(obj.chunk_size))
    print('Byte range: {}'.format(obj.data_byte_range))

    counter = {}
    data = obj.data_stream.read()

    print('Data lenght: {}'.format(len(data)))

    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1
    return counter


def simple_reduce_function(results):
    """general purpose reduce function that sums up the results
    of previous activations of map functions  """
    total = 0
    for map_result in results:
        total = total + map_result
    return total


def my_reduce_function(results):
    """sums up the number of words by totaling the number of appearances of each word.
    @param results: dictionary that counts the appearances of each word within a url."""
    final_result = 0
    for count in results:
        for word in count:
            final_result += count[word]
    return final_result


def my_cloudobject_put(obj, storage):
    """uploads to storage pickled dict of type: {word:number of appearances} """
    counter = my_map_function_obj(obj, 0)
    cloudobject = storage.put_cloudobject(pickle.dumps(counter))
    return cloudobject


def my_cloudobject_get(cloudobjects, storage):
    """unpickles list of data from storage and return their sum by using a reduce function """
    data = [pickle.loads(storage.get_cloudobject(co)) for co in cloudobjects]
    return my_reduce_function(data)


def my_map_function_storage(key_i, bucket_name, storage):
    print(f'I am processing the object /{bucket_name}/{key_i}')
    counter = {}
    data = storage.get_object(bucket_name, key_i)
    for line in data.splitlines():
        for word in line.decode('utf-8').split():
            if word not in counter:
                counter[word] = 1
            else:
                counter[word] += 1
    return counter


class SideEffect:
    def __init__(self):
        pass

    @property
    def foo(self):
        raise RuntimeError("Side effect triggered")

    result = 5


def passthrough_function(x):
    return x.result


def raise_value_error(x):
    raise ValueError('worker failed')


def sleep_seconds(x):
    time.sleep(x)
    return x


def echo_object(obj):
    data = obj.data_stream.read()
    return data.decode() if isinstance(data, bytes) else data


def echo_env_flag(x):
    return os.environ.get('LITHOPS_TEST_FLAG')
