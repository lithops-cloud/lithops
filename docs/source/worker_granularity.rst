Worker Granularity
==================

Lithops was initially designed with Function as a Service (FaaS) platforms in mind. As such, its default worker 
granularity is set to 1. This means that each function activation is executed within its own isolated 
runtime instance. This design choice aligns with the nature of FaaS, where functions are typically short-lived 
and stateless, making it well-suited for tasks like event-driven processing and serverless computing.

However, it's essential to understand the distinctions between FaaS and Container as a Service (CaaS) platforms. 
In CaaS, you have greater flexibility in selecting the appropriate resources (CPU and memory) for each worker. 
This flexibility allows you to fine-tune the execution environment to your specific requirements. In contrast 
to FaaS, where the granularity is often fixed at 1, CaaS platforms enable you to adjust the number of CPUs 
allocated to a container.

When using Lithops on a CaaS platform, it can be more advantageous to increase the number of CPUs assigned to each
worker and subsequently adjust the granularity, rather than adhering to a 1:1 granularity ratio. This approach
significantly reduces cold start times. For instance, if you need to execute 100 tasks with a 1:1 granularity, 
it would attempt to initiate all 100 containers simultaneously, potentially overloading the CaaS platform. However, 
by configuring each worker to utilize 4 CPUs and updating Lithops accordingly, it would only need to start 25 containers. 
This allows you to leverage the resource flexibility provided by CaaS without attempting to impose FaaS-like granularity. 
Understanding these distinctions between FaaS and CaaS platforms is crucial for optimizing the performance and efficient 
resource utilization of your Lithops-based applications.

How to customize worker granularity?
------------------------------------

To customize the worker granularity, you first need to use the ``worker_processes`` parameter.
The ``worker_processes`` config parameter is employed to define the number of parallel sub-workers
initiated within a single worker. To fully utilize the allocated resources for your containers,
it is advisable to set this parameter to a value that matches or exceeds the number of CPUs in
your container or VM. 

You can provide the ``worker_processes`` parameter either in the Lithops config, under the
compute backend section:

.. code:: yaml

    gcp_cloudrun:
        ....
        worker_processes : 4

or during a ``FunctionExecutor()`` instantiation:

.. code:: python

    import lithops

    fexec = lithops.FunctionExecutor(worker_processes=4)


Alongside the ``worker_processes`` configuration parameter, it is possible to specify the ``chunksize`` parameter.
The ``chunksize`` parameter determines the number of functions allocated to each worker for processing.
By default, the ``chunksize`` parameter is automatically configured to match the ``worker_processes``. However, you have the 
flexibility to customize it by setting it to a higher value. For example, if you have 200 tasks to execute and you set 
``worker_processes`` to 4 and ``chunksize`` to 8, this configuration will result in the initiation of 25 workers (instead of 50).
Within each worker, 4 parallel sub-workers will start execution. Each worker will receive 8 tasks to process. The first 4 
tasks will begin immediately since there are 4 available sub-workers per worker. Meanwhile, the remaining 4 tasks will be 
queued for execution as the initial tasks start to complete.


To customize the ``chunksize`` parameter, you have to edit your ``map()`` or ``map_reduce()`` calls and specify the desirde value, for example:

.. code:: python

    import lithops


    def my_map_function(id, x):
        print(f"I'm activation number {id}")
        return x + 7


    if __name__ == "__main__":
        fexec = lithops.FunctionExecutor(worker_processes=4)
        fexec.map(my_map_function, range(200), chunksize=8)
        print(fexec.get_result())


Worker granularity in the standalone mode using VMs
---------------------------------------------------

In addition to supporting FaaS and CaaS platforms, Lithops also extends its compatibility to Virtual Machine (VM) backends, 
such as EC2. Similar to CaaS environments, VMs offer a high degree of resource customization. When utilizing VMs with Lithops, 
you gain the ability to tailor your VM instance with the appropriate resources, including CPU cores. In scenarios where 
parallelism is crucial, it may be more efficient to configure a VM with a higher core count, such as 16 CPUs, rather than 
attempting to manage and coordinate eight separate VM instances with single cores each. This approach simplifies resource 
management and optimizes the performance of your Lithops-based applications running on VM backends. As with CaaS, 
understanding the flexibility VMs provide is essential for effectively utilizing your compute resources.

Unlike FaaS and CaaS platforms, when deploying Lithops on Virtual Machine backends, such as EC2, a master-worker architecture
is adopted. In this paradigm, the master node holds a work queue containing tasks for a specific job, and workers pick up and
process tasks one by one. In this sense, the chunksize parameter, which determines the number of functions allocated
to each worker for parallel processing, is not applicable in this context. Consequently, the worker granularity is inherently
determined by the number of worker processess in the VM setup. Adjusting the number of VM instances or the configuration of
each VM, such as the CPU core count, becomes crucial for optimizing performance and resource utilization in this master-worker
approach.

In this scenario, specifying either the ``worker_instance_type`` or ``worker_processes`` config parameter is enough to achieve
the desired parallelism inside worker VMs. By default, Lithops determines the total number of worker processes based on the
number of CPUs in the specified instance type. For example, an AWS EC2 instance of type ``t2.medium``, with 2 CPUs, would set
``worker_processes`` to 2. Additionally, users have the flexibility to manually adjust parallelism by setting a different
value for ``worker_processes``. Depending on the use case, it would be convenient to set more ``worker_processes`` than CPUs,
or less ``worker_processes`` than CPUs. For example, we can use a ``t2.medium`` instance types that has 2 CPUs, but
set ``worker_processes`` to 4:

.. code:: python

    import lithops


    def my_map_function(id, x):
        print(f"I'm activation number {id}")
        return x + 7


    if __name__ == "__main__":
        fexec = lithops.FunctionExecutor(worker_instance_type='t2.medium', worker_processes=4)
        fexec.map(my_map_function, range(50))
        print(fexec.get_result())
