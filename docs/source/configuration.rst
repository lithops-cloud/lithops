.. _config:

Configuration
=============

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
