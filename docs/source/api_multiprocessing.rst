Multiprocessing API
===================

Lithops implements Python's `multiprocessing API <https://docs.python.org/3/library/multiprocessing.html>`_ to transparently run local-parallel applications but using serverless functions for Processes and a Redis instance for shared state and Inter-Process Communication (IPC).

Before utilizing this API, you will need to install its dependencies:

.. code-block:: bash

   python3 -m pip install lithops[multiprocessing]


Process and Pool
----------------

`Processes <https://docs.python.org/3/library/multiprocessing.html#the-process-class>`_ and `Pool <https://docs.python.org/3/library/multiprocessing.html#using-a-pool-of-workers>`_ are the abstractions used in multiprocessing to parallelize computation. They interact directly with Lithops' Core API.

.. code:: python

    # from multiprocessing import Process
    from lithops.multiprocessing import Process


    def my_process_function(name):
        print(f'Hello {name}!')

    p = Process(target=my_process_function, args=('World',))
    p.start()
    p.join()

.. code:: python

    # from multiprocessing import Pool, TimeoutError
    from lithops.multiprocessing import Pool, TimeoutError

    def square(x):
        return x * x

    with Pool() as pool:
        async_result = pool.map_async(square, [1, 2, 3, 4, 5])
        try:
            result = async_result.get(timeout=3)
            print(result)
        except TimeoutError:
            print("Timed out!")

.. note:: ``Process`` and ``Pool`` need no Redis instance. Everything under
   `Stateful abstractions`_ does.

What is not supported
---------------------

The API is the standard one, but the runtime is not a local operating system,
so a few things of it have no counterpart:

.. list-table::
   :header-rows: 1

   * - Call
     - Behaviour
   * - ``active_children()``, ``parent_process()``
     - Raise ``NotImplementedError``. There is no process tree to walk
   * - ``Process.terminate()``, ``Process.is_alive()``, ``Process.exitcode``
     - Raise ``NotImplementedError``. Lithops cannot recall an activation it
       already dispatched, nor report on one
   * - ``Pool.imap()``, ``Pool.imap_unordered()``
     - Not lazy: every call is submitted and every result collected before the
       first one is yielded, so an endless iterable will not work. The results
       always come back in the order of the input
   * - ``Pool.terminate()``
     - Gives the Lithops executor back and stops the calls still in flight,
       so the ``AsyncResult`` of one of them has nothing left to return.
       Close and join the pool instead when the results are still wanted
   * - ``Pool(maxtasksperchild=...)``, ``Process.daemon``, ``Process.authkey``
     - Accepted and ignored. Workers are ephemeral, so there is nothing to
       recycle, nothing to daemonize and no handshake to authenticate
   * - ``RLock``
     - Only re-entrant for the object that took it. A copy of it in another
       process, or one restored from a pickle, does not know the lock is held
   * - ``Semaphore.acquire()``, ``Lock.acquire()``
     - Take ``block``, but no ``timeout``
   * - ``Condition.wait(timeout)``
     - A wait that timed out leaves its token behind, so the next
       ``notify()`` may wake nobody. ``notify_all()`` is not affected
   * - ``RawArray('c', ...)``
     - Not implemented. Use ``Array('c', ...)``
   * - ``Process.close()``
     - Releases the executor whatever state the call is in. The standard
       library refuses to close a process still running; Lithops cannot tell
       without asking storage, and the activation outlives the object anyway
   * - ``freeze_support()``, ``allow_connection_pickling()``,
       ``set_executable()``, ``set_forkserver_preload()``
     - Accepted and do nothing. There is no re-executed parent, no local
       interpreter to point at and no fork server

Everything else that ``multiprocessing`` exports is here under the same name,
including ``ProcessError``, ``BufferTooShort``, ``TimeoutError``,
``AuthenticationError``, ``get_logger()`` and ``log_to_stderr()``, and
``ThreadPool`` under ``lithops.multiprocessing.pool``.

.. note:: ``TimeoutError`` is the one of this package, not the builtin of the
   same name, exactly as in the standard library. Catch it by importing it::

       from lithops.multiprocessing import Pool, TimeoutError

Stateful abstractions
---------------------

Lithops also implements all stateful abstractions from Python multiprocessing: Queue, Pipes, Shared memory, Events, etc.

Since FaaS lacks mechanisms for function-to-function communication, a `Redis <https://redis.io/>`_ database instance is used.

.. note:: Redis is required for **every** shared object: ``Pipe``, ``Queue``,
   ``SimpleQueue``, ``JoinableQueue``, ``Lock``, ``RLock``, ``Semaphore``,
   ``BoundedSemaphore``, ``Condition``, ``Event``, ``Barrier``, ``Value``,
   ``Array`` and ``Manager``. Building any of them without a ``redis`` section
   in the configuration raises an error.

.. note:: Both the functions and the Lithops orchestrator (local process) must be able to access the Redis instance. For example, deploying it on your local machine won't work, since the cloud functions won't be able to reach it.

The Redis credentials (host, password, etc.) are loaded from the ``redis`` section of the Lithops configuration.

The fastest way to deploy a Redis instance is using Docker in a VM located in the cloud of your choice:

.. code:: bash

    docker run --rm -d --network host --name redis redis:6.2.1 --requirepass redispassword

To reduce latency, you can deploy the functions and the VM in the same VPC, so that they communicate over internal traffic instead of the public internet.
For example, in AWS, the functions and the VM can be deployed in the same VPC: Lambdas go in a private subnet and the VM in a public subnet. This way, the VM has access to the internet and the local Lithops process can also reach it.

Extra multiprocessing configuration
-----------------------------------

The Lithops multiprocessing module has extra configuration specific to the multiprocessing functionality.
To preserve transparency, the functions and method signatures remain completely compatible with the original multiprocessing module.
For this reason, to set specific configuration at runtime, the ``lithops.multiprocessing.config`` module is used:

.. code:: python

    import lithops.multiprocessing as mp
    from lithops.multiprocessing import config as mp_config


    def my_map_function(x):
        return x + 7


    if __name__ == "__main__":
        iterdata = [1, 2, 3, 4]

        # To set a config parameter, use the set_parameter
        # function and specify the parameter and the desired value
        mp_config.set_parameter(mp_config.LITHOPS_CONFIG, {'lithops': {'backend': 'localhost'}})
        mp_config.set_parameter(mp_config.STREAM_STDOUT, True)
        mp_config.set_parameter(mp_config.REDIS_EXPIRY_TIME, 1800)
        mp_config.set_parameter(mp_config.PIPE_CONNECTION_TYPE, 'redislist')
        mp_config.set_parameter(mp_config.ENV_VARS, {'ENVVAR': 'hello'})
        mp_config.set_parameter(mp_config.EXPORT_EXECUTION_DETAILS, '.')

        with mp.Pool() as pool:
            results = pool.map(my_map_function, iterdata)

        print(results)

Multiprocessing configuration keys
..................................

.. list-table::
   :header-rows: 1

   * - Key
     - Description
     - Default
   * - LITHOPS_CONFIG
     - Lithops configuration, passed directly to the Lithops FunctionExecutor
     - ``{}``
   * - STREAM_STDOUT
     - Stream processes STDOUT to the local terminal through Redis pubsub
     - ``False``
   * - REDIS_EXPIRY_TIME
     - Expiry time for used Redis keys
     - ``3600`` (1 hour)
   * - PIPE_CONNECTION_TYPE
     - Connection type for the ``Pipe`` abstraction. Can be ``redislist`` to use Redis or ``nanomsg`` for direct function-to-function communication using NanoMSG\*
     - ``redislist``
   * - ENV_VARS
     - Environment variables for the processes, passed directly to Lithops FunctionExecutor ``extra_env`` argument
     - ``{}``
   * - EXPORT_EXECUTION_DETAILS
     - Calls ``lithops.FunctionExecutor.plot()``, pass a path to store the plots, ``False`` to disable it
     - ``False``

``lithops.multiprocessing.config.reset()`` puts every parameter back to its
default. The parameters are process-wide, so a library that sets one changes
what every pool of that process sees.


\* To use nanomsg for Pipes, you must still deploy a Redis instance (used for the pipe directory). Note that this feature only works in environments where functions can open a port and communicate with each other.
