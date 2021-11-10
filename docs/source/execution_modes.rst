Execution Modes
===============

Lithops compute backends can be classified in 3 different execution modes depending on the backend you choose.


Localhost mode
--------------
This mode allows to run functions in your local machine, using the available local CPUs.
This is the default mode of execution if no configuration is provided.

.. note:: This is the preferable option for starting with Lithops, and for testing (debugging) your applications.

.. code:: python

    fexec = lithops.LocalhostExecutor()


- Available backends: `Localhost <compute_config/localhost.md>`_


Serverless mode
---------------
This mode allows to run functions by using one or multiple function-as-a-service (FaaS)
Serverless compute backends.  In this mode of execution, each function invocation equals
to a parallel task running in the cloud in an isolated environment.

In this mode of execution, the execution environment depends of the serverless compute
backend. For example, in AWS Lambda, IBM Cloud Functions, Google Cloud Run, IBM Code Engine
and Kubernetes you must use a Docker image as execution environment. In contrast,
Google cloud functions, Azure functions and Aliyun Functions use their own formats of environments.

.. code:: python

    fexec = lithops.ServerlessExecutor()


- Available backends: `IBM Cloud Functions <compute_config/ibm_cf.md>`_, `IBM Code Engine <compute_config/code_engine.md>`_, `AWS Lambda <compute_config/aws_lambda.md>`_, `AWS Batch <compute_config/aws_batch.md>`_, `Google Cloud Functions <compute_config/gcp_functions.md>`_, `Google Cloud Run <compute_config/gcp_cloudrun.md>`_, `Azure Functions <compute_config/azure_functions.md>`_, `Aliyun Function Compute <compute_config/aliyun_functions.md>`_, `Kubernetes Jobs <compute_config/k8s_job.md>`_, `Knative <compute_config/knative.md>`_, `OpenWhisk <compute_config/openwhisk.md>`_


Standalone mode
---------------
This mode allows to run functions by using a remote host or a cluster of virtual machines (VM).
In the VM, functions run using parallel processes. This mode of executions is similar to the
localhost mode, but using remote machines. In this case, it is not needed to install anything
in the remote VMs since Lithops does this process automatically the first time you use them.

.. note:: This is the preferable option if your application (or a part) requires a more powerful environment than the ones provided by the Serverless backends (in terms of CPU and Memory).

.. code:: python

    fexec = lithops.StandaloneExecutor()

- Available backends: `IBM Virtual Private Cloud <compute_config/ibm_vpc.md>`_, `AWS Elastic Compute Cloud <compute_config/aws_ec2.md>`_, `Remote host / Virtual Machine <compute_config/vm.md>`_
