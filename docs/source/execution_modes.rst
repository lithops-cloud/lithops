Execution Modes
===============

Lithops compute backends can be classified in 3 different execution modes depending 
on the backend you choose.


Localhost mode
--------------
The "localhost mode" in Lithops is a convenient feature that enables you to execute 
functions on your local machine using processes, without relying on cloud resources 
or serverless computing environments. It serves as the default execution 
mode if no specific configuration is provided.

To use localhost mode, you can simply write your functions using the Lithops programming 
model and execute them locally. Lithops will handle the distribution and coordination 
of the function executions, optimizing performance by leveraging multiple processes.

This mode is particularly useful for development, testing, and debugging purposes,
as it eliminates the need to deploy code to a cloud environment during the 
development phase.


.. note:: This is the preferable option for starting with Lithops, and for testing (debugging) your applications.

.. code:: python

    fexec = lithops.LocalhostExecutor()


- Available backends: `Localhost <compute_config/localhost.md>`_


Serverless mode
---------------
The "serverless mode" in Lithops is designed to execute functions using publicly 
accessible serverless compute services, including IBM Cloud Functions, Amazon Lambda, 
Google Cloud Functions, and more, enabling parallel task execution in isolated cloud 
environments.

In serverless mode, Lithops leverages the power of these serverless platforms to execute 
functions as independent tasks. Each function invocation is treated as a separate parallel 
task, benefiting from the scalability, automatic provisioning of resources, and isolation 
provided by the serverless compute service.

By utilizing serverless platforms, developers can offload the burden of managing 
infrastructure and focus solely on writing and deploying their functions. 
The serverless mode in Lithops abstracts away the complexities of configuring and 
scaling embarrassingly parallel applications, making it easier to develop and deploy 
large-scale data processing workloads.

This execution mode offers flexibility and elasticity, as resources are dynamically 
allocated based on workload demands, ensuring efficient utilization of compute power. 
It allows developers to seamlessly leverage the scalability and reliability of 
serverless platforms while benefiting from Lithops' programming model and distributed 
computing capabilities.

.. code:: python

    fexec = lithops.ServerlessExecutor()


- Available backends: `IBM Cloud Functions <compute_config/ibm_cf.md>`_, `IBM Code Engine <compute_config/code_engine.md>`_, `AWS Lambda <compute_config/aws_lambda.md>`_, `AWS Batch <compute_config/aws_batch.md>`_, `Google Cloud Functions <compute_config/gcp_functions.md>`_, `Google Cloud Run <compute_config/gcp_cloudrun.md>`_, `Azure Functions <compute_config/azure_functions.md>`_, `Azure Container APPs <compute_config/azure_containers.md>`_, `Aliyun Function Compute <compute_config/aliyun_functions.md>`_, `Oracle Functions <compute_config/oracle_functions.md>`_, `Kubernetes Jobs <compute_config/kubernetes.md>`_, `Knative <compute_config/knative.md>`_, `Singularity <compute_config/singularity.md>`_, `OpenWhisk <compute_config/openwhisk.md>`_


Standalone mode
---------------
The "standalone mode" in Lithops provides the capability to execute functions on one 
or multiple virtual machines (VMs) simultaneously, in a serverless-like fashion, 
without requiring manual provisioning as everything is automatically created. 
This mode can be deployed in a private cluster or in the cloud, where functions 
within each VM are executed using parallel processes.

In standalone mode, Lithops simplifies the deployment and management of VMs, enabling 
users to effortlessly scale their compute resources to meet the demands of their workloads. 
By leveraging the automatic creation and configuration of VMs provided by Lithops, 
developers can focus on writing their functions while Lithops takes care of the 
underlying infrastructure.

.. note:: This is the preferable option if your application (or a part) requires a more powerful environment than the ones provided by the Serverless backends (in terms of CPU and Memory).

.. code:: python

    fexec = lithops.StandaloneExecutor()

- Available backends: `IBM Virtual Private Cloud <compute_config/ibm_vpc.md>`_, `AWS Elastic Compute Cloud (EC2) <compute_config/aws_ec2.md>`_, `Azure Virtual Machines <compute_config/azure_vms.md>`_, `Virtual Machine <compute_config/vm.md>`_
