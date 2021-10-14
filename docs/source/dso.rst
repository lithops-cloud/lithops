Distributed shared objects
==========================

.. warning:: This feature is experimental and as such is unstable. Using it in production is discouraged. Expect errors and API/functionality changes in future releases.

.. note:: Currently it only works with IBM Cloud Functions

Usage
-----

1. Deploy a custom runtime as follows:

.. code::

    lithops runtime build -f runtime/ibm_cf/Docker.dso id/runtime:tag
    lithops runtime create id/runtime:tag

1. Create a DSO server in the Cloud following the instructions available here: https://github.com/crucial-project/dso/tree/2.0

2. Run a script using a command of the form ``"DSO=IP:11222" python3 my_script.py``, where `DSO` is the address of a running DSO deployment.

Examples
--------

.. code:: python

    from dso.client import Client
    from jpype import *
    from jpype import java
    import lithops
    import os

    dso = os.environ.get('DSO')


    def my_map_function(id, x):
        client = Client(dso)
        c = client.getAtomicCounter("cnt")
        c.increment(x)
        b = client.getCyclicBarrier("b", len(iterdata))
        b.waiting()
        return c.tally()


    if __name__ == "__main__":
        f = Client(dso)
        c = f.getAtomicCounter("cnt")
        c.reset()
        iterdata = [1, 2, 3, 4]
        fexec = lithops.FunctionExecutor(runtime='0track/lithops-dso:1.1')
        fexec.map(my_map_function, iterdata)
        print(fexec.get_result())
        print(c.tally())
        fexec.clean()


.. code:: python

    from dso.client import Client
    from jpype import *
    from jpype import java
    import lithops
    import os

    dso = os.environ.get('DSO')


    def my_function(x):
        client = Client(dso)
        d = client.getAtomicCounter("cnt")
        return d.increment(x)


    if __name__ == '__main__':
        fexec = lithops.FunctionExecutor(runtime='0track/lithops-dso:1.1')
        fexec.call_async(my_function, 3)
        client = Client(dso)
        c = client.getAtomicCounter("cnt")
        print("counter: " + str(c.tally()))
        print(fexec.get_result())
        print("counter: " + str(c.tally()))

