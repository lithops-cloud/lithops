What is Lithops?
****************

**Lithops is a Python multi-cloud serverless computing framework. It allows to run unmodified local python code at massive scale in the main serverless computing platforms.**

Lithops delivers the user’s code into the cloud without requiring knowledge of how it is deployed and run.
Moreover, its multicloud-agnostic architecture ensures portability across cloud providers, overcoming vendor lock-in.

------------

**Lithops provides great value for data-intensive applications like Big Data analytics and embarrassingly parallel jobs.**

It is specially suited for highly-parallel programs with little or no need for communication between processes.

Examples of applications that run with Lithops include Monte Carlo simulations, deep learning and machine learning processes, metabolomics computations, and geospatial
analytics, to name a few.

------------

**Lithops facilitates consuming data from object storage (like AWS S3, GCP Storage or IBM Cloud Object Storage) by providing automatic partitioning and data discovery for common data formats like CSV.**

Lithops abstracts away the underlying cloud-specific APIs for accessing storage and provides an intuitive and easy to use interface to process high volumes of data.


Use any Cloud
*************
**Lithops provides an extensible backend architecture that is designed to work with different compute and storage services available on Cloud providers and on-premise backends.**

In this sense, you can code your application in Python and run it unmodified wherever your data is located at: IBM Cloud, AWS, Azure, Google Cloud and Alibaba Aliyun...

.. image:: source/images/multicloud.jpg
   :alt: Available backends
   :align: center

|

Quick Start
***********

Lithops is available for Python 3.6 and up. Install it using ``pip``:

.. code-block::

    pip install -U lithops

You're ready to execute a simple example!

.. code:: python

    from lithops import FunctionExecutor

    def hello(name):
        return 'Hello {}!'.format(name)

    with FunctionExecutor() as fexec:
        fut = fexec.call_async(hello, 'World')
        print(fut.result())


Additional resources
********************

Blogs and Talks
---------------
* `Simplify the developer experience with OpenShift for Big Data processing by using Lithops framework <https://medium.com/@gvernik/simplify-the-developer-experience-with-openshift-for-big-data-processing-by-using-lithops-framework-d62a795b5e1c>`_
* `Speed-up your Python applications using Lithops and Serverless Cloud resources <https://itnext.io/speed-up-your-python-applications-using-lithops-and-serverless-cloud-resources-a64beb008bb5>`_
* `Serverless Without Constraints <https://www.ibm.com/cloud/blog/serverless-without-constraints>`_
* `Lithops, a Multi-cloud Serverless Programming Framework <https://itnext.io/lithops-a-multi-cloud-serverless-programming-framework-fd97f0d5e9e4>`_
* `CNCF Webinar - Toward Hybrid Cloud Serverless Transparency with Lithops Framework <https://www.youtube.com/watch?v=-uS-wi8CxBo>`_
* `Using Serverless to Run Your Python Code on 1000 Cores by Changing Two Lines of Code <https://www.ibm.com/cloud/blog/using-serverless-to-run-your-python-code-on-1000-cores-by-changing-two-line-of-code>`_
* `Decoding dark molecular matter in spatial metabolomics with IBM Cloud Functions <https://www.ibm.com/cloud/blog/decoding-dark-molecular-matter-in-spatial-metabolomics-with-ibm-cloud-functions>`_
* `Your easy move to serverless computing and radically simplified data processing <https://www.slideshare.net/gvernik/your-easy-move-to-serverless-computing-and-radically-simplified-data-processing-238929020>`_ Strata Data Conference, NY 2019
* `Speed up data pre-processing with Lithops in deep learning <https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/>`_
* `Predicting the future with Monte Carlo simulations over IBM Cloud Functions <https://www.ibm.com/cloud/blog/monte-carlo-simulations-with-ibm-cloud-functions>`_
* `Process large data sets at massive scale with Lithops over IBM Cloud Functions <https://www.ibm.com/cloud/blog/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions>`_
* `Industrial project in Technion on Lithops <http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/>`_

Papers
------
* `Outsourcing Data Processing Jobs with Lithops <https://ieeexplore.ieee.org/document/9619947>`_ - IEEE Transactions on Cloud Computing 2022
* `Towards Multicloud Access Transparency in Serverless Computing <https://www.computer.org/csdl/magazine/so/5555/01/09218932/1nMMkpZ8Ko8>`_ - IEEE Software 2021
* `Primula: a Practical Shuffle/Sort Operator for Serverless Computing <https://dl.acm.org/doi/10.1145/3429357.3430522>`_ - ACM/IFIP International Middleware Conference 2020. `See Primula presentation here <https://www.youtube.com/watch?v=v698iu5YfWM>`_
* `Bringing scaling transparency to Proteomics applications with serverless computing <https://dl.acm.org/doi/abs/10.1145/3429880.3430101>`_ - 6th International Workshop on Serverless Computing (WoSC6) 2020. `See Workshop presentation here <https://www.serverlesscomputing.org/wosc6/#p10>`_
* `Serverless data analytics in the IBM Cloud <https://dl.acm.org/citation.cfm?id=3284029>`_ - ACM/IFIP International Middleware Conference 2018


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
