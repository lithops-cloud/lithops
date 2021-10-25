Configuration
=============

.. note:: By default, if no configuration is provided, Lithops will use the `Localhost <compute_config/localhost.html>`_ backend to run the functions.

To work with Lithops on the Cloud, you must configure at least one compute backend and one storage backend.
Lithops can work both with the leading cloud providers, and using on-premise or Kubernetes platforms.
You have multiple options to choose compute and storage backends based on your needs.

Lithops configuration can be provided either using a **configuration file**, or in runtime via a **python dictionary.**


Compute and Storage backends
----------------------------

Choose your compute and storage engines from the table below:

+--------------------------------------------------------------------+--------------------------------------------------------------------+
| Compute backends                                                   | Storage Backends                                                   |
+====================================================================+====================================================================+
|| `Localhost <compute_config/localhost.html>`_                      || `IBM Cloud Object Storage <storage_config/ibm_cos.html>`_         |
|| `IBM Cloud Functions <compute_config/ibm_cf.html>`_               || `AWS S3 <storage_config/aws_s3.html>`_                            |
|| `IBM Code Engine <compute_config/code_engine.html>`_              || `Google Cloud Storage <storage_config/gcp_storage.html>`_         |
|| `AWS Lambda <compute_config/aws_lambda.html>`_                    || `Azure Blob Storage <storage_config/azure_blob.html>`_            |
|| `Google Cloud Functions <compute_config/gcp_functions.html>`_     || `Aliyun Object Storage Service <storage_config/aliyun_oss.html>`_ |
|| `Google Cloud Run <compute_config/gcp_cloudrun.html>`_            || `Infinispan <storage_config/infinispan.html>`_                    |
|| `Azure Functions <compute_config/azure_functions.html>`_          || `Ceph <storage_config/ceph.html>`_                                |
|| `Aliyun Function Compute <compute_config/aliyun_functions.html>`_ || `MinIO <storage_config/minio.html>`_                              |
|| `Kubernetes Jobs <compute_config/k8s_job.html>`_                  || `Redis <storage_config/redis.html>`_                              |
|| `Knative <compute_config/knative.html>`_                          || `OpenStack Swift <storage_config/swift.html>`_                    |
|| `OpenWhisk <compute_config/openwhisk.html>`_                      ||                                                                   |
|| `Remote Host / Virtual Machine <compute_config/vm.html>`_         ||                                                                   |
|| `IBM Virtual Private Cloud <compute_config/ibm_vpc.html>`_        ||                                                                   |
+--------------------------------------------------------------------+--------------------------------------------------------------------+

Configuration File
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