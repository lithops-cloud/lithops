Comparing Lithops with Other Distributed Computing Frameworks
=============================================================

Lithops introduces a novel approach to distributed computing by leveraging **serverless functions** for massively parallel computations. Unlike traditional frameworks that require managing a cluster of nodes, Lithops utilizes Function-as-a-Service (FaaS) platforms to dynamically scale execution resources — down to zero when idle and massively up when needed.

In addition, Lithops offers a simple and consistent programming interface to transparently process data stored in **Object Storage** from within serverless functions. Its **modular and cloud-agnostic architecture** enables seamless portability across different cloud providers and FaaS platforms, effectively avoiding vendor lock-in.

PyWren
------

`PyWren <http://pywren.io/>`_ is the precursor to Lithops. Initially designed to run exclusively on AWS Lambda using a Conda runtime and supporting only Python 2.7, it served as a proof of concept for using serverless functions in scientific computing.

In 2018, the Lithops team forked PyWren to adapt it for **IBM Cloud Functions**, which offered a Docker-based runtime. This evolution also introduced support for **Object Storage as a primary data source** and opened the door to more advanced use cases such as Big Data analytics.

By September 2020, the IBM PyWren fork had diverged significantly. The maintainers rebranded the project as **Lithops**, reflecting its broader goals — including multi-cloud compatibility, improved developer experience, and support for modern Python environments and distributed computing patterns.

For more details, refer to the Middleware'18 industry paper:  
`Serverless Data Analytics in the IBM Cloud <https://dl.acm.org/doi/10.1145/3284028.3284029>`_.

Ray and Dask
------------

.. image:: https://github.com/ray-project/ray/raw/master/doc/source/images/ray_logo.png
   :align: center
   :width: 250

.. image:: https://docs.dask.org/en/stable/_images/dask_horizontal.svg
   :align: center
   :width: 250


`Ray <https://ray.io/>`_ and `Dask <https://dask.org/>`_ are distributed computing frameworks designed to operate on a **predefined cluster of nodes** (typically virtual machines). In contrast, Lithops relies on **serverless runtimes**, which allows for *elastic and fine-grained scaling* — including scaling to zero — with no idle infrastructure costs.

While Ray and Dask provide dynamic task scheduling and can autoscale within an IaaS environment, they always require a **centralized "head node" or controller** to manage the cluster, making them less suitable for ephemeral and cost-efficient cloud-native computing.

Additionally, the performance and elasticity of Ray and Dask in IaaS environments are not directly comparable to Lithops' **fully serverless model**, which benefits from the near-infinite parallelism offered by cloud functions.

PySpark
-------

.. image:: https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Apache_Spark_logo.svg/2560px-Apache_Spark_logo.svg.png
   :align: center
   :width: 250

`PySpark <https://spark.apache.org/docs/latest/api/python/>`_ is the Python interface for Apache Spark, a well-established distributed computing engine. Spark is typically deployed on a **static cluster of machines**, either on-premises or in cloud environments using HDFS or cloud-native file systems.

PySpark is optimized for **batch analytics** using DataFrames and SparkSQL, but it lacks native integration with FaaS models. Its operational model is not inherently elastic and requires continuous management of a Spark cluster, which may not align with modern, fully managed, or serverless computing paradigms.

Serverless Framework
--------------------

.. image:: https://cdn.diegooo.com/media/20210606183353/serverless-framework-icon.png
   :align: center
   :width: 250

`Serverless Framework <https://www.serverless.com/>`_ is a deployment toolchain designed primarily for **building and deploying serverless web applications**, especially on AWS, GCP, and Azure. It is widely used to manage HTTP APIs, event-driven services, and infrastructure-as-code (IaC) for cloud-native apps.

Although both Lithops and Serverless Framework leverage **serverless functions**, their objectives are fundamentally different:

- **Serverless Framework** focuses on application deployment (e.g., microservices, REST APIs).
- **Lithops** targets **parallel and data-intensive workloads**, enabling large-scale execution of Python functions over scientific datasets, data lakes, and unstructured data in object storage.

Summary
-------

Lithops stands out as a **cloud-native, serverless-first framework** purpose-built for **parallel computing, data analytics, and scientific workloads**. By abstracting away infrastructure management and providing built-in object storage integration, it delivers a unique balance of **simplicity**, **performance**, and **multi-cloud compatibility** — distinguishing it from traditional cluster-based frameworks and generic serverless tools alike.
