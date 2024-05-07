Multiprocessing API
===================

Lithops implements Python's `multiprocessing API <https://docs.python.org/3/library/multiprocessing.html>`_ to transparently run local-parallel applications but using serverless functions for Processes and a Redis instance for shared state and Inter-Process Communication (IPC).

Before utilizing this API, you will need to install its dependencies:

.. code-block:: bash

   python3 -m pip install lithops[multiprocessing]


Process and Pool
----------------

`Processes <https://docs.python.org/3/library/multiprocessing.html#the-process-class>`_ and `Pool <https://docs.python.org/3/library/multiprocessing.html#using-a-pool-of-workers>`_ are the abstractions used in multiprocessing to parallelize computation. They interact directly with Lithop's Futures API.

.. code:: python

    # from multiprocessing import Process
    from lithops.multiprocessing import Process


    def my_process_function(name):
        print(f'Hello {name}!)

    p = Process(target=my_process_function, args=('World',))
    p.start()
    p.join()

.. code:: python

    # from multiprocessing import Pool
    from lithops.multiprocessing import Pool

    def square(x):
        return x * x

    with Pool() as pool:
        async_result = pool.map_async(square, [1, 2, 3, 4, 5])
        try:
            result = async_result.get(timeout=3)
            print(result)
        except TimeoutError:
            print("Timed out!")

Stateful abstractions
---------------------

Lithops also implements all stateful abstractions from Python mutliprocessing: Queue, Pipes, Shared memory, Events...

Since FaaS lacks mechanisms for function-to-function communication, a `Redis <https://redis.io/>`_ database instance node is used.

.. note:: Both the functions and the Lithops orchestrator local process must be able to access the Redis instance -- for example, deploying it in your local machine won't work

The Redis credentials (host, password...) is loaded from the ``redis`` section of the Lithops configuration.

The fastest way to deploy a Redis instance is using Docker in a VM located in the cloud of your choice:

.. code:: bash

    docker run --rm -d --network host --name redis redis:6.2.1 --requirepass redispassword

To have lower latency, you can deploy the functions and the VM in the same VPC and use route through internal traffic instead of the internet.
For example, in AWS, the functions and VM can be deployed in the same VPC: Lambdas go to a private subnet and the VM in a public subnet. This way, the VM has access to the internet and the local Lithops process can also access it.

Extra multiprocessing configuration
-----------------------------------

The Lithops multiprocessing module has extra configuration specific to the multiprocessing functionality.
To preserve transparency, the functions and method signature has remain completely compatible with the original multiprocessing module.
For this reason, to set specific configuration in runtime, the ``Lithops.multiprocessing.config`` module is used:

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
     - Lithops configuration, passed directly to Lithop's FunctionExecutor
     - ``{}``
   * - STREAM_STDOUT
     - Stream processes STDOUT to the local terminal through Redis pubsub
     - ``False``
   * - REDIS_EXPIRY_TIME
     - Expiry time for used Redis keys
     - ``3600`` (1 hour)
   * - PIPE_CONNECTION_TYPE
     - Connection type for the ``Pipe`` abstraction, can be ``redislist`` for using Redis or ``nanomsg`` for function-to-function direct communication using NanoMSG*
     - ``redislist``
   * - ENV_VARS
     - Environment variables for the processes, passed directly to Lithops FunctionExecutor ``extra_env`` argument
     - ``{}``
   * - EXPORT_EXECUTION_DETAILS
     - Calls ``lithops.FunctionExecutor.plot()``, pass a path to store the plots, ``None`` to disable it
     - ``None``


* To use nanomsg for Pipes, you must still deploy a Redis instance (used for pipe directory). Note that this feature only works in environments where functions can open a port and communicate with each other.
