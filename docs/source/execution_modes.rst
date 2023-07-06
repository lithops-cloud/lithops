Execution Modes
===============

Lithops compute backends can be classified in 3 different execution modes depending on the backend you choose.


Localhost mode
--------------
The "localhost mode" in Lithops is a convenient feature that enables you to execute functions on your local machine using processes. It serves as the default execution mode if no specific configuration is provided.

In localhost mode, you can run your code locally without relying on cloud resources or serverless computing environments. It allows you to leverage the power of Lithops and its distributed computing capabilities right on your own machine.

By utilizing processes, Lithops efficiently manages the execution of functions in parallel, taking advantage of the available resources on your local system. This mode is particularly useful for development, testing, and debugging purposes, as it eliminates the need to deploy code to a cloud environment during the development phase.

To use localhost mode, you can simply write your functions using the Lithops programming model and execute them locally. Lithops will handle the distribution and coordination of the function executions, optimizing performance by leveraging multiple processes.

Whether you're exploring Lithops for the first time or working on local development tasks, the localhost mode offers a seamless experience, empowering you to harness the capabilities of Lithops without the need for cloud infrastructure.

.. note:: This is the preferable option for starting with Lithops, and for testing (debugging) your applications.

.. code:: python

    fexec = lithops.LocalhostExecutor()


- Available backends: `Localhost <compute_config/localhost.md>`_


Serverless mode
---------------
The "serverless mode" in Lithops is designed to execute functions using publicly accessible serverless compute services, including IBM Cloud Functions, Amazon Lambda, Google Cloud Functions, and more, enabling parallel task execution in isolated cloud environments.

In serverless mode, Lithops leverages the power of these serverless platforms to execute functions as independent tasks. Each function invocation is treated as a separate parallel task, benefiting from the scalability, automatic provisioning of resources, and isolation provided by the serverless compute service.

By utilizing serverless platforms, developers can offload the burden of managing infrastructure and focus solely on writing and deploying their functions. The serverless mode in Lithops abstracts away the complexities of configuring and scaling embarrassingly parallel applications, making it easier to develop and deploy large-scale data processing workloads.

This execution mode offers flexibility and elasticity, as resources are dynamically allocated based on workload demands, ensuring efficient utilization of compute power. It allows developers to seamlessly leverage the scalability and reliability of serverless platforms while benefiting from Lithops' programming model and distributed computing capabilities.

Whether you're processing large datasets, handling real-time event-driven tasks, or building serverless applications, Lithops' serverless mode provides a convenient and scalable approach to execute functions on popular serverless compute services, simplifying the development and deployment process.

.. code:: python

    fexec = lithops.ServerlessExecutor()


- Available backends: `IBM Cloud Functions <compute_config/ibm_cf.md>`_, `IBM Code Engine <compute_config/code_engine.md>`_, `AWS Lambda <compute_config/aws_lambda.md>`_, `AWS Batch <compute_config/aws_batch.md>`_, `Google Cloud Functions <compute_config/gcp_functions.md>`_, `Google Cloud Run <compute_config/gcp_cloudrun.md>`_, `Azure Functions <compute_config/azure_functions.md>`_, `Azure Container APPs <compute_config/azure_containers.md>`_, `Aliyun Function Compute <compute_config/aliyun_functions.md>`_, `Kubernetes Jobs <compute_config/k8s_job.md>`_, `Knative <compute_config/knative.md>`_, `OpenWhisk <compute_config/openwhisk.md>`_


Standalone mode
---------------
The "standalone mode" in Lithops provides the capability to execute functions on one or multiple virtual machines (VMs) simultaneously, in a serverless-like fashion, without requiring manual provisioning as everything is automatically created. This mode can be deployed in a private cluster or in the cloud, where functions within each VM are executed using parallel processes, similar to the functionality offered in localhost mode.

In standalone mode, Lithops simplifies the deployment and management of VMs, enabling users to effortlessly scale their compute resources to meet the demands of their workloads. By leveraging the automatic creation and configuration of VMs, developers can focus on writing their functions while Lithops takes care of the underlying infrastructure.

Each VM within the standalone mode operates independently, allowing for parallel processing of functions. This parallelism enhances performance and enables efficient execution of computationally intensive tasks across multiple VMs. Whether deployed in a private cluster or in the cloud, standalone mode provides flexibility and scalability to process large volumes of data or perform complex computations.

Standalone mode in Lithops expands the possibilities for distributed computing by combining the convenience of serverless-like provisioning with the power of parallel processing on VMs. It offers developers a seamless experience for executing functions in an isolated and scalable environment, simplifying the development and execution of data-intensive workloads and parallel applications.

.. note:: This is the preferable option if your application (or a part) requires a more powerful environment than the ones provided by the Serverless backends (in terms of CPU and Memory).

.. code:: python

    fexec = lithops.StandaloneExecutor()

- Available backends: `IBM Virtual Private Cloud <compute_config/ibm_vpc.md>`_, `AWS Elastic Compute Cloud (EC2) <compute_config/aws_ec2.md>`_, `Azure Virtual Machines <compute_config/azure_vms.md>`_, `Virtual Machine <compute_config/vm.md>`_
