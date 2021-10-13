.. _config:

Configuration
=====================

To work with Lithops you must configure both compute and storage backends. Failing to configure them properly will
prevent Lithops to submit workloads.

Lithops can work with almost any compute backend and storage any can be used with almost any cloud provider. You have
multiple options to choose compute backend and storage backend based on your needs.

After you choose your compute and storage engine, you need to configure Lithops so it can use chosen compute and
storage. Lithops configuration can be provided either in configuration file or provided in runtime via Python
dictionary.

Configuration file
------------------

To configure Lithops through a `configuration file <https://github.com/lithops-cloud/lithops/blob/master/config/config_template.yaml>`_
you have multiple options:

1. Create e new file called ``config`` in the ``~/.lithops`` folder.

2. Create a new file called ``.lithops_config`` in the root directory of your project from where you will execute your
   Lithops scripts.

3. Create the config file in any other location and configure the `LITHOPS_CONFIG_FILE` system environment variable
indicating the absolute or relative location of the configuration file:

.. code-block::

   LITHOPS_CONFIG_FILE=<CONFIG_FILE_LOCATION>

Configuration keys in runtime
-----------------------------

An alternative mode of configuration is to use a Python dictionary. This option allows to pass all the configuration
details as part of the Lithops invocation in runtime. You can see an entire list of configuration keys at the
:ref:`config-reference-label` section.

Here is an example of providing configuration keys for IBM Cloud Functions and IBM Cloud Object Storage:

.. code:: python

    import lithops

    config = {'lithops': {'backend': 'ibm_cf', storage: 'ibm_cos'},
              'ibm_cf':  {'endpoint': 'ENDPOINT',
                          'namespace': 'NAMESPACE',
                          'api_key': 'API_KEY'},
              'ibm_cos': {'storage_bucket': 'BUCKET_NAME',
                          'region': 'REGION',
                          'api_key': 'API_KEY'}}

    def hello_world(name):
        return 'Hello {}!'.format(name)

    if __name__ == '__main__':
        fexec = lithops.FunctionExecutor(config=config)
        fexec.call_async(hello_world, 'World')
        print(fexec.get_result())

Lithops Monitoring
------------------

By default, Lithops uses the storage backend to monitor function activations: Each function activation stores a file
named *{id}/status.json* to the Object Storage when it finishes its execution. This file contains some statistics about
the execution, including if the function activation ran successfully or not. Having these files, the default monitoring
approach is based on listing the Object Store objects (polling) each X seconds to know which function activations have
finished and which not.

As this default approach can slow-down the total application execution time, due to the number of requests it has to
make against the object store, in Lithops we integrated a RabbitMQ service to monitor function activations in real-time.
With RabbitMQ, the content of the *{id}/status.json* file is sent trough a queue. This speeds-up total application execution
time, since Lithops only needs one connection to the messaging service to monitor all function activations. We currently
support the AMQP protocol.

.. note:: The RabbitMQ server has to be accessible from both the client and the functions. For example, it could be deployed in a cloud server with a public IP with AMQP port open (5672).

To enable Lithops to use this service, add the *AMQP_URL* key into the *rabbitmq* section in
the configuration, for example:

.. code:: yaml

    rabbitmq:
        amqp_url: <AMQP_URL>  # amqp://

In addition, activate the monitoring service by setting ``monitoring: rabbitmq`` in the configuration (Lithops section):

.. code:: yaml

    lithops:
       monitoring: rabbitmq


.. code:: python

    fexec = lithops.FunctionExecutor(monitoring='rabbitmq')


Dynamic runtime customization
-----------------------------

This new feature enables early preparation of Lithops workers with the map function and custom Lithops 
runtime already deployed, and ready to be used in consequent computations. This can reduce overall map/reduce 
computation latency significantly, especially when the computation overhead (pickle stage) is long compared to 
the actual computation performed at the workers.

To activate this mode, set to True the "customized_runtime" property under "serverless" section of the config file.

Warning: to protect your privacy, use a private docker registry instead of public docker hub.

.. code:: yaml

    lithops:
       customized_runtime: True


.. _config-reference-label:

Configuration Reference
-----------------------

Lithops Config Keys
~~~~~~~~~~~~~~~~~~~

.. csv-table::
   :file: lithops_config_keys.csv
   :delim: ;
   :widths: 5 5 20 10 60
   :header-rows: 1


Standalone Config Keys
~~~~~~~~~~~~~~~~~~~~~~

.. csv-table::
   :file: standalone_config_keys.csv
   :delim: ;
   :widths: 5 5 20 10 60
   :header-rows: 1
