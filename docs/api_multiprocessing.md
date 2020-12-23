# Lithops Multiprocessing API Details

Lithops allows to use the standard Python [multiprocessing](https://docs.python.org/3/library/multiprocessing.html) High-level API to run functions by using a cloud compute backend.

## Process

The [`Process`](https://docs.python.org/3/library/multiprocessing.html#process-and-exceptions) class is used to execute a single function on the cloud compute backend. First, the function is set up when the `Process` class is instantiated.
Then, using the `start()` method, the function is executed remotely and asynchronously. The `join()` method is used to block until the function has finished.

```python
from lithops.multiprocessing import Process

def f(name):
    print('hello', name)

if __name__ == '__main__':
    p = Process(target=f, args=('bob',))
    p.start()
    p.join()
```

An example is provided [here](../examples/multiprocessing/process.py)


## Pool

The [`Pool`](https://docs.python.org/3/library/multiprocessing.html#module-multiprocessing.pool) is a higher level abstraction that represents a set of worker functions.
It has methods which allows tasks to be offloaded to the worker processes in a few different ways.

| Parameter | Description | Default |
|---|---|---|
| processes | Number of processes that form the pool. | `workers` parameter from Lithops configuration. |
| initargs | Configuration for Lithops [FunctionExecutor](./api_futures.md)  | `None` (Default Lithops configuration). |

An example is provided [here](../examples/multiprocessing/pool.py)

### Pool API Reference

- **apply()**

Call synchronously to *func* with arguments *args* and keyword arguments *kwds*. It blocks until the result is ready.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| args | Function positional arguments.  | `()` |
| kwds | Function key-word arguments.  | `{}` |

- **apply_async()**

A variant of the `apply()` method which returns an `AsyncResult` object.
Call asynchronously to *func* with arguments *args* and keyword arguments *kwds*.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| args | Function positional arguments.  | `()` |
| kwds | Function key-word arguments.  | `{}` |

- **map()**

A parallel equivalent of the `map()` built-in function (it supports only one iterable argument though, for multiple iterables see `starmap()`).

It applies *func* to every item of *iterable*. Returns a list containing the results. It blocks until the result is ready.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| iterable | Iterable of elements to map to. | - |

- **map_async()**

A variant of the `map()` method which returns a `AsyncResult` object.

It asynchronously applies *func* to every item of *iterable*. Returns an `AsyncResult` instance.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| iterable | Iterable of elements to map to. | - |

- **imap()**

`imap` interfaces directly to `map`. It is kept for compatibility with `muliprocessing` module.

- **imap_unordered()**

`imap_unordered` interfaces directly to `map`. It is kept for compatibility with `muliprocessing` module.

- **starmap()**

Like `map()` except that the elements of the *iterable* list are expected to be iterables that are unpacked as arguments.

Hence an iterable of `[(1,2), (3, 4)]` results in `[func(1,2), func(3,4)]`.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| iterable | Iterable of tuples of elements to map to. | - |

- **starmap_async()**

A combination of `starmap()` and `map_async()` that iterates over iterable of iterables and calls *func* with the iterables unpacked.
Returns an `AsyncResult` object.

| Parameter | Description | Default |
|---|---|---|
| func | Target callable. | - |
| iterable | Iterable of tuples of elements to map to. | - |

- **close()**

Prevents any more tasks from being submitted to the pool.

- **terminate()**

Cleans all data related to worker processes, but it does not stop the worker processes immediately without completing outstanding work.
When the pool object is garbage collected, `terminate()` is called.

- **join()**

Wait for the worker processes to exit. `close()` or `terminate()` must be called before using `join()`.

### AsyncResult API reference

`Pool.apply_async()` and `Pool.map_async()` return an instance of `AsyncResult`. 

- **get()**

Return the result when it arrives.
If *timeout* is not `None` and the result does not arrive within *timeout* seconds then `multiprocessing.TimeoutError` is raised.
If the remote call raised an exception then that exception will be reraised by `get()`.

| Parameter | Description | Default |
|---|---|---|
| timeout | Timeout seconds. | `None` |

- **wait()**

Wait until the result is available or until *timeout* seconds pass.

| Parameter | Description | Default |
|---|---|---|
| timeout | Timeout seconds. | `None` |

- **ready()**

Return whether the call has completed.

- **successful()**

Return whether the call completed without raising an exception. Will raise `ValueError` if the result is not ready.

## Processes communication, synchronization and shared state

Python's `multiprocessing` module provides several shared state and synchronization primitives to communicate processes.

This is accomplished by accessing a remote [Redis](https://redis.io/download) instance.
Redis configuration must be set up in [`~/home/.lithops/config`](../config/README.md) file, under `redis` section:

```yaml
redis:
    host : 127.0.0.1
    port : 6379
    password: 123456789
```

It is **required** Redis version 6.0.
This Redis instance **must** be accessible from both the client (local) Lithops orchestrator process and the functions that run on a compute backend.
The easiest and most straight forward way to deploy Redis is using Docker or other container runtimes:
```
$ docker run --rm -it --network host --name redis redis:6.0.5-buster --requirepass changeme123
```
While the container is running, Redis will be accessible at default port `6379`.

### Pipe

Returns a pair `(conn1, conn2)` of `Connection` objects representing the ends of a pipe.
If *duplex* is `True` then the pipe is bidirectional, if not, then the pipe is unidirectional: `conn1` can only be used for receiving messages and `conn2` can only be used for sending messages.

| Parameter | Description | Default |
|---|---|---|
| duplex | Bidirectional connection. | `True` |

An example is provided [here](../examples/multiprocessing/pipe.py)

#### Connection API reference

- **send()**

Send an object to the other end of the connection which should be read using `recv()`. The object must be picklable.

| Parameter | Description | Default |
|---|---|---|
| obj | Object to send. Must be picklable. | - |

- **recv()**

Return an object sent from the other end of the connection using `send()`. Blocks until there is something to receive.

| Parameter | Description | Default |
|---|---|---|
| obj | Object to send. Must be picklable. | - |

- **close()**

Close the connection.

- **poll()**

Check if there is any data available to be read.
If *timeout* is set, then it blocks until *timeout* seconds pass. If timeout is `None` then an infinite timeout is used.

| Parameter | Description | Default |
|---|---|---|
| timeout | Seconds to wait for receiving an object. | - |

- **send_bytes()**

Send byte data from a bytes-like object as a complete message. If *offset* is given then data is read from that position in buffer.
If *size* is given then that many bytes will be read from buffer. 

| Parameter | Description | Default |
|---|---|---|
| buffer | Bytes-like buffer object to send. | - |
| offset | Send next bytes from offset position. | `None` |
| size | Amount of bytes to send from offset position. | `None` |

- **recv_bytes()**

Return a complete message of byte data sent from the other end of the connection as a string.
Blocks until there is something to receive.

If *maxlength* is specified and the message is longer than *maxlength* then `OSError` is raised and the connection will no longer be readable.

| Parameter | Description | Default |
|---|---|---|
| maxlength | Maximum size of bytes willing to be read. | - |

- **recv_bytes_into()**

Read into *buffer* a complete message of byte data sent from the other end of the connection and return the number of bytes in the message.
Blocks until there is something to receive. *buffer* must be a writable bytes-like object.
If *offset* is given then the message will be written into the buffer from that position.

### Queue

Returns a process shared queue implemented using a pipe and a few locks/semaphores.
When a process first puts an item on the queue a feeder thread is started which transfers objects from a buffer into the pipe.

| Parameter | Description | Default |
|---|---|---|
| maxsize | Maximum number of elements that can be queued in the queue. | - |

An example is provided [here](../examples/multiprocessing/queue_poll.py)

#### Queue API reference

- **qsize()**

Returns the number of elements in the queue.

- **empty()**

Return `True` if the queue is empty, `False` otherwise.

- **full()**

Return `True` if the queue is full, `False` otherwise.

- **put()**

Put *obj* into the queue. If the optional argument *block* is `True` (the default) and *timeout* is `None` (the default), block if necessary until a free slot is available.
If *timeout* is set, then it blocks at most timeout seconds and raises the `queue.Full` exception if no free slot was available within that time.

| Parameter | Description | Default |
|---|---|---|
| obj | Object to put into the queue. Must be picklable. | - |
| block | `True` to block until there is a free spot in the queue. | `False` |
| timeout | If `block` is `True`, wait for timeout seconds. | `None` |

- **put_nowait()**

Equivalent to `put(obj, False)`.

- **get()**

Remove and return an item from the queue.
If *block* is `True` and `timeout` is `None`, it blocks until an item is available.
If `timeout` is set, it blocks at most timeout seconds and raises the `queue.Empty` exception if no item was available within that time.

| Parameter | Description | Default |
|---|---|---|
| block | `True` to block until there is an object to get from the queue. | `False` |
| timeout | If `block` is `True`, wait for timeout seconds. | `None` |

- **get_nowait()**

Equivalent to `get(False)`.

- **close()**

Indicate that no more data will be put on this queue by the current process.

- **join_thread()**

Join the background feeder thread. This can only be used after `close()` has been called.
It blocks until the background thread exits, ensuring that all data in the buffer has been flushed to the pipe.

- **cancel_join_thread()**

Terminates background thread if it has stuck blocked. Not waiting for the feeder thread to put data into the queue might cause data loss.

### SimpleQueue

It is a simplified `Queue` type, very close to a locked `Pipe`.

An example is provided [here](../examples/multiprocessing/simple_queue.py)

#### SimpleQueue API reference

- **close()**

It releases internal resources.
A queue must not be used anymore after it is closed. For example, `get()`, `put()` and `empty()` methods must no longer be called.

- **empty()**

Return `True` if the queue is empty, `False` otherwise.

- **get()**

Remove and return an item from the queue.

- **put()**

Put *item* into the queue.

| Parameter | Description | Default |
|---|---|---|
| item | Object to put into the queue. Must be picklable | - |

### JoinableQueue

A `Queue` subclass. It is a queue which additionally has `task_done()` and `join()` methods.

An example is provided [here](../examples/multiprocessing/joinable_queue.py)

#### JoinableQueue API reference

- **task_done()**

Indicate that a formerly enqueued task is complete. Used by queue consumers.
For each `get()` used to fetch a task, a subsequent call to `task_done()` tells the queue that the processing on the task is complete.

If a `join()` is currently blocking, it will resume when all items have been processed (meaning that a `task_done()` call was received for every item that had been `put()` into the queue).
Raises a `ValueError` if called more times than there were items placed in the queue.

- **join()**

Block until all items in the queue have been gotten and processed.
When the count of unfinished tasks drops to zero, `join()` unblocks.

### Barrier

Create a barrier object for parties number of processes.
An *action*, when provided, is a callable to be called by one of the threads when they are released.
`timeout` is the default timeout value if none is specified for the `wait()` method.

| Parameter | Description | Default |
|---|---|---|
| parties | Number of processes to wait for to unlock the barrier. | - |
| action | Callable that one process executes when the processes are released. | `None` |
| timeout | Barrier wait timeout seconds. | `None` |

An example is provided [here](../examples/multiprocessing/barrier.py)

#### Barrier API reference

- **wait()**

Pass the barrier. When all the threads party to the barrier have called this function, they are all released simultaneously.
If a timeout is provided, it is used in preference to any that was supplied to the class constructor.

| Parameter | Description | Default |
|---|---|---|
| item | Object to put into the queue. Must be picklable | - |

- **reset()**

Return the barrier to the default, empty state. Any threads waiting on it will receive the `BrokenBarrierError` exception.

- **abort()**

Put the barrier into a broken state. This causes any active or future calls to `wait()` to fail with the `BrokenBarrierError`.

- **parties**

The number of threads required to pass the barrier.

- **n_waiting**

The number of threads currently waiting in the barrier.

- **broken**

A boolean that is `True` if the barrier is in the broken state.

### Semaphore

This class implements semaphore objects. A semaphore manages an atomic counter representing the number of `release()` calls minus the number of `acquire()` calls, plus an initial *value*.
The `acquire()` method blocks if necessary until it can return without making the counter negative. If not given, `value` defaults to 1.

| Parameter | Description | Default |
|---|---|---|
| value | Semaphore initial value. | 1 |

An example is provided [here](../examples/multiprocessing/semaphore.py)

#### Semaphore API reference

- **acquire()**

Acquire a semaphore.
If the internal counter is larger than zero on entry, decrement it by one and return `True` immediately.
If the internal counter is zero on entry, block until awoken by a call to `release()`.
Once awoken (and the counter is greater than 0), decrement the counter by 1 and return `True`.
Exactly one thread will be awoken by each call to `release()`.

| Parameter | Description | Default |
|---|---|---|
| blocking | Block until the semaphore is released. | `False` |

- **release()**

Release a semaphore, incrementing the internal counter by one.
When it was zero on entry and other threads are waiting for it to become larger than zero again, wake up one of those threads.

### BoundedSemaphore

A `Semaphore` subclass. A bounded semaphore checks to make sure its current value doesn’t exceed its initial value.

### Condition

This class implements condition variable objects. A condition variable allows one or more threads to wait until they are notified by another thread.
If the lock argument is given and not `None`, it must be a `Lock` or `RLock` object, and it is used as the underlying lock.

| Parameter | Description | Default |
|---|---|---|
| lock | Condition lock. | `None` |

#### Condition API reference

- **acquire()**

Acquire the underlying lock.

- **release()**

Release the underlying lock.

- **wait()**

Wait until notified or until a *timeout* occurs.

| Parameter | Description | Default |
|---|---|---|
| timeout | Timeout seconds for waiting. | `None` |

- **wait_for()**

Wait until a condition evaluates to true. `predicate` should be a callable which result will be interpreted as a boolean value.
A timeout may be provided giving the maximum time to wait.

- **notify()**

Wake up one thread waiting on this condition, if any.

- **notify_all()**

Wake up all threads waiting on this condition. This method acts like `notify()`, but wakes up all waiting threads instead of one.

### Event

Class implementing event objects. An event manages a flag that can be set to true with the `set()` method and reset to false with the `clear()` method.
The `wait()` method blocks until the flag is true. The flag is initially `False`.

#### Event API reference

- **is_set()**

Return `True` if the internal flag is true.

- **set()**

Set the internal flag to true. All threads waiting for it to become true are awakened.

- **clear()**

Reset the internal flag to false.

- **wait(timeout=None)**

Block until the internal flag is true or until the optional *timeout* occurs.

### Lock

Mutual exclusion lock.
Once a process or thread has acquired a lock, subsequent attempts to acquire it from any process or thread will block until it is released; any process or thread may release it.

An example is provided [here](../examples/multiprocessing/lock.py)

#### Lock API reference

- **acquire()**

Acquire a lock. If *block* is set, the method call will block until the lock is in an unlocked state, then set it to locked and return `True`.
If not, it does not block and returns `False` if the lock is unlocked. Otherwise, set the lock to a locked state and return `True`. 

| Parameter | Description | Default |
|---|---|---|
| block | Block until the lock is released. | `True` |

- **release()**

Release a lock.

### RLock

A `Lock` subclass. A recursive lock must be released by the process or thread that acquired it.
Once a process or thread has acquired a recursive lock, the same process or thread may acquire it again without blocking;
that process or thread must release it once for each time it has been acquired.


### Value

By default the return value is actually a synchronized wrapper for the object.
The object itself can be accessed via the `value` attribute of a `Value`.
*typecode_or_type determines* determines the type and size allocated for the shared object.
If *lock*, a new lock is created to synchronize access to the value. It can be acessed using method `get_lock()`.

| Parameter | Description | Default |
|---|---|---|
| typecode_or_type | Ctype of the shared value. | - |
| lock | Create a lock for the shared value. | `True` |

An example is provided [here](../examples/multiprocessing/counter.py)

### Array

A subclass of `Value`. Instead of sharing a single value, `Array` is used to share a list of values.

An example is provided [here](../examples/multiprocessing/array.py)

### Manager

Managers provide a way to create data which can be shared between different processes.

An example is provided [here](../examples/multiprocessing/manager.py)

Managers are used to share objects between processed. However, for now, only a limited set of shared objects
can be created using `Manager()`:

1. **Barrier()**: Create a shared [threading.Barrier](https://docs.python.org/3/library/threading.html#threading.Barrier) object and return a proxy for it.
2. **BoundedSemaphore()**: Create a shared [threading.BoundedSemaphore](https://docs.python.org/3/library/threading.html#threading.BoundedSemaphore) object and return a proxy for it.
3. **Condition()**: Create a shared [threading.Condition](https://docs.python.org/3/library/threading.html#threading.Condition) object and return a proxy for it.
4. **Event()**: Create a shared [threading.Event](https://docs.python.org/3/library/threading.html#threading.Event) object and return a proxy for it.
5. **Lock()**: Create a shared [threading.Lock](https://docs.python.org/3/library/threading.html#threading.Lock) object and return a proxy for it.
6. **Namespace()**: Create a shared [Namespace](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.managers.Namespace) object and return a proxy for it.
7. **Queue()**: Create a shared [queue.Queue](https://docs.python.org/3/library/queue.html#queue.Queue) object and return a proxy for it.
8. **RLock()**: Create a shared [threading.RLock](https://docs.python.org/3/library/threading.html#threading.RLock) object and return a proxy for it.
9. **Semaphore()**: Create a shared [threading.Semaphore](https://docs.python.org/3/library/threading.html#threading.Semaphore) object and return a proxy for it.
10. **Array()**: Create an array and return a proxy for it.
11. **Value()**: Create an object with a writable value attribute and return a proxy for it.
12. **dict()**: Create a shared [dict](https://docs.python.org/3/library/stdtypes.html#dict) object and return a proxy for it.
13. **list()**: Create a shared list object and return a proxy for it.
