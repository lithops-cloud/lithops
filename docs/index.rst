Welcome to Lithops!
********************

**Lithops is a Python multi-cloud serverless computing framework** that empowers you to **run unmodified Python code at massive scale** on leading serverless platforms and beyond.

Whether you're processing terabytes of data or launching thousands of parallel tasks, Lithops lets you **focus on your code, not infrastructure**. It brings simplicity, performance, and flexibility to cloud-native computing.


Why Lithops?
============

Serverless computing makes it easy to run code in the cloud — but scaling data-intensive workloads across clouds is hard. Lithops solves this by providing:

- ✅ **Zero-configuration scale-out**: Run your Python functions on thousands of cloud workers with no infrastructure management.
- 🌍 **True multi-cloud portability**: Move seamlessly between AWS, GCP, Azure, IBM Cloud, etc...
- 💡 **Developer-first experience**: Write standard Python code, including NumPy, pandas, and scikit-learn — no cloud-specific boilerplate required.
- 🧠 **Optimized for big data and AI**: Efficiently process massive datasets stored in object storage services with automatic partitioning.


What You Can Build
===================

Lithops is ideal for **highly parallel, data-heavy workloads**. These include:

- 🔁 Monte Carlo simulations
- 🧬 Metabolomics and genomics pipelines
- 🗺️ Geospatial analytics
- 🧠 Deep learning and hyperparameter tuning
- 📊 Big Data ETL and analytics workflows

If your problem can be broken down into many small, independent tasks, Lithops will help you solve it at scale — fast.

Key Features
============

Compute Anywhere
----------------
**Lithops features a modular and extensible backend architecture**, allowing you to run workloads across:

- Serverless functions
- Cloud VMs and Kubernetes clusters
- On-premise compute resources

No matter where your data lives, Lithops can execute your code right next to it.

.. image:: source/images/multicloud.jpg
   :alt: Available backends
   :align: center


Object Storage Made Easy
-------------------------

**Seamlessly process large-scale data stored in object storage.**

Lithops simplifies working with data lakes and object storage by providing:

- 🔍 **Automatic data discovery**: Detects and lists files across nested directories.
- 📂 **Transparent data partitioning**: Splits large files (e.g., CSV, Parquet, JSON) into chunks for efficient parallel processing.
- 🧰 **Unified, Pythonic API**: Interact with your data using a single interface, regardless of where it's stored.

You write simple Python code — Lithops handles the complexity of parallel I/O, data distribution, and storage backends under the hood.


Get Started Quickly
====================

To start using Lithops:

1. Install via pip:

   .. code-block:: bash

      pip install lithops

2. Configure your cloud credentials (see the full guide in :doc:`/config`)

3. Write and run your first parallel job:

   .. code-block:: python

      import lithops

      def my_function(x):
          return x * 2

      fexec = lithops.FunctionExecutor()
      fexec.map(my_function, range(10))
      print(fexec.get_result())

You're now running massively parallel workloads with just a few lines of code!


Success stories
===============

* `Metaspace Metabolomics Platform <https://metaspace2020.eu/>`_ is running in production in AWS with hundreds of users.
  MetaSpace is using Lithops over Lambda Functions and EC2 VMs to access metabolomics data in Amazon S3.
  MetaSpace moved from Spark to Lithops to simplify dynamic and elastic resource provisioning.

* `OpenNebula Open Source Cloud and Edge Computing platform <https://opennebula.io/>`_ integrates Lithops as an easy-to-use appliance
  for data analytics. OpenNebula also deploys MinIO storage and Lithops Kubernetes backend to facilitate data analytics
  in on-premise and edge deployments.

* `Cubed <https://github.com/cubed-dev/cubed/tree/main>`_ is a popular library for scalable multidimensional array processing with bounded memory.
  Cubed is a drop-in replacement for Dask's Array API.
  Cubed integrates Lithops as a fast compute backend enabling scalable array processing in the Cloud.

* `BSC Marenostrum 5 SuperComputer <https://www.bsc.es/marenostrum/marenostrum-5>`_ is a pre-exascale EuroHPC supercomputer with
  a peak computational power of 314 PFlops. A new Lithops HPC compute backend has been created enabling large-scale computing
  reaching tens of thousands of concurrent functions. LithopsHPC is now being used in the neardata.eu project for extreme
  data analytics of genomics pipelines.


Blogs and Talks
===============

* `Simplify the developer experience with OpenShift for Big Data processing by using Lithops framework
  <https://medium.com/@gvernik/simplify-the-developer-experience-with-openshift-for-big-data-processing-by-using-lithops-framework-d62a795b5e1c>`_

* `Speed-up your Python applications using Lithops and Serverless Cloud resources
  <https://itnext.io/speed-up-your-python-applications-using-lithops-and-serverless-cloud-resources-a64beb008bb5>`_

* `Serverless Without Constraints
  <https://www.ibm.com/blog/serverless-without-constraints>`_

* `Lithops, a Multi-cloud Serverless Programming Framework
  <https://itnext.io/lithops-a-multi-cloud-serverless-programming-framework-fd97f0d5e9e4>`_

* `CNCF Webinar - Toward Hybrid Cloud Serverless Transparency with Lithops Framework
  <https://www.youtube.com/watch?v=-uS-wi8CxBo>`_

* `Using Serverless to Run Your Python Code on 1000 Cores by Changing Two Lines of Code
  <https://www.ibm.com/blog/using-serverless-to-run-your-python-code-on-1000-cores-by-changing-two-line-of-code>`_

* `Decoding dark molecular matter in spatial metabolomics with IBM Cloud Functions
  <https://www.ibm.com/blog/decoding-dark-molecular-matter-in-spatial-metabolomics-with-ibm-cloud-functions>`_

* `Your easy move to serverless computing and radically simplified data processing
  <https://www.slideshare.net/gvernik/your-easy-move-to-serverless-computing-and-radically-simplified-data-processing-238929020>`_  
  Strata Data Conference, NY 2019

* `Speed up data pre-processing with Lithops in deep learning
  <https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/>`_

* `Predicting the future with Monte Carlo simulations over IBM Cloud Functions
  <https://www.ibm.com/blog/monte-carlo-simulations-with-ibm-cloud-functions>`_

* `Process large data sets at massive scale with Lithops over IBM Cloud Functions
  <https://www.ibm.com/blog/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions>`_

* `Industrial project in Technion on Lithops
  <http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/>`_


Papers
======

* `Serverful Functions: Leveraging Servers in Complex Serverless Workflows
  <https://dl.acm.org/doi/10.1145/3700824.3701095>`_ - ACM Middleware Industrial Track 2024

* `Transparent serverless execution of Python multiprocessing applications
  <https://dl.acm.org/doi/10.1016/j.future.2022.10.038>`_ - Elsevier Future Generation Computer Systems 2023

* `Outsourcing Data Processing Jobs with Lithops
  <https://ieeexplore.ieee.org/document/9619947>`_ - IEEE Transactions on Cloud Computing 2022

* `Towards Multicloud Access Transparency in Serverless Computing
  <https://www.computer.org/csdl/magazine/so/5555/01/09218932/1nMMkpZ8Ko8>`_ - IEEE Software 2021

* `Primula: a Practical Shuffle/Sort Operator for Serverless Computing
  <https://dl.acm.org/doi/10.1145/3429357.3430522>`_ - ACM/IFIP International Middleware Conference 2020.  
  `See Primula presentation here <https://www.youtube.com/watch?v=v698iu5YfWM>`_

* `Bringing scaling transparency to Proteomics applications with serverless computing
  <https://dl.acm.org/doi/abs/10.1145/3429880.3430101>`_ - 6th International Workshop on Serverless Computing (WoSC6) 2020.  
  `See Workshop presentation here <https://www.serverlesscomputing.org/wosc6/#p10>`_

* `Serverless data analytics in the IBM Cloud
  <https://dl.acm.org/citation.cfm?id=3284029>`_ - ACM/IFIP International Middleware Conference 2018


Join the Community
==================

Lithops is an open-source project, actively maintained and supported by a community of contributors and users. You can:

- 💬 Join the discussion on `GitHub Discussions <https://github.com/lithops-cloud/lithops/discussions>`_
- 🐞 Report issues or contribute on `GitHub <https://github.com/lithops-cloud/lithops>`_
- 📖 Read more in the full documentation


---

**Start writing scalable cloud applications — with Lithops.**


.. toctree::
   :hidden:

   self


.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Overview of Lithops

   source/design.rst
   source/comparing_lithops.rst
   source/supported_clouds.rst
   source/execution_modes.rst
   source/cli.rst

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Install and Configure Lithops

   source/install_lithops.rst
   source/configuration.rst
   source/compute_backends.rst
   source/storage_backends.rst

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Lithops Compute API

   source/api_futures.rst
   source/functions.md
   source/worker_granularity.rst
   source/notebooks/function_chaining.ipynb
   source/api_stats.rst

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Lithops Storage API

   source/api_storage.md

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Data Processing

   source/data_processing.md
   source/data_partitioning.md

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Integrations

   source/api_multiprocessing.rst
   source/api_storage_os.md
   source/sklearn_joblib.rst
   source/airflow.rst

.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Advanced Features

   source/monitoring.rst
   Custom Runtimes <https://github.com/lithops-cloud/lithops/tree/master/runtime>


.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Experimental Features

   source/metrics.rst
   source/dso.rst


.. toctree::
   :hidden:
   :maxdepth: 0
   :caption: Developer Guide

   Applications <https://github.com/lithops-cloud/applications>
   source/contributing.rst
   Changelog <https://github.com/lithops-cloud/lithops/blob/master/CHANGELOG.md>
