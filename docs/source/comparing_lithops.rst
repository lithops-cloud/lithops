Comparing Lithops with other distributed computing frameworks
=============================================================

In a nutshell, Lithops differs from other distributed computing frameworks in that Lithops leverages serverless
functions to compute massively parallel computations.

In addition, Lithops provides a simple and easy-to-use interface to access and process data stored in Object Storage
from your serverless functions.

Moreover, Lithops abstract design allows seamlessly portability between clouds and FaaS services, avoiding vendor
lock-in.

PyWren
------

.. image:: https://www.faasification.com/assets/img/tools/pywren-logo-big.png
   :align: center
   :width: 250


`PyWren <http://pywren.io/>`_  is Lithops' "father" project. PyWren was only designed to run in AWS Lambda with a
Conda environment and only supported Python 2.7. In 2018, Lithops' creators forked PyWren and adapted it to IBM Cloud
Functions, which, in contrast, uses a Docker runtime. The authors also explored new usages for PyWren, like processing Big Data from
Object Storage. Then, on September 2020, IBM PyWren authors decided that the project had evolved enough to no longer be
considered a simple fork of PyWren for IBM cloud and became Lithops. With this change, the project would no longer be
tied to the old PyWren model and could move to more modern features such as mulit-cloud support or the transparent
multiprocessing interface.

You can read more about PyWren IBM Cloud at the Middleware'18 industry paper `Serverless Data Analytics in the IBM Cloud <https://dl.acm.org/doi/10.1145/3284028.3284029>`_.

Ray and Dask
------------

.. image:: https://warehouse-camo.ingress.cmh1.psfhosted.org/98ae79911b7a91517ba16ef2dc7dc3b972214820/68747470733a2f2f6769746875622e636f6d2f7261792d70726f6a6563742f7261792f7261772f6d61737465722f646f632f736f757263652f696d616765732f7261795f6865616465725f6c6f676f2e706e67
   :align: center
   :width: 250

.. image:: https://docs.dask.org/en/stable/_images/dask_horizontal.svg
   :align: center
   :width: 250


In comparison with Lithops, both `Ray <https://ray.io/>`_ and `Dask <https://dask.org/>`_ leverage a cluster of nodes for distributed computing, while Lithops
mainly leverages serverless functions. This restraint makes Ray much less flexible than Lithops in terms of scalability.

Although Dask and Ray can scale and adapt the resources to the amount of computation needed, they don't scale to zero since
they must keep a "head node" or "master" that controls the cluster and must be kept up.

In any case, the capacity and scalability of Ray or Dask in IaaS using virtual machines is not comparable to that of serverless functions.

PySpark
-------

.. image:: https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Apache_Spark_logo.svg/2560px-Apache_Spark_logo.svg.png
   :align: center
   :width: 250


Much like Ray or Dask, PySpark is a distributed computing framework that uses cluster technologies. PySpark provides Python bindings for Spark.
Spark is designed to work with a fixed-size node cluster, and it is typically used to process data from on-prem HDFS
and analyze it using SparkSQL and Spark DataFrame.


Serverless Framework
--------------------

.. image:: https://cdn.diegooo.com/media/20210606183353/serverless-framework-icon.png
   :align: center
   :width: 250


Serverless Framework is a tool to develop serverless applications (mainly NodeJS) and deploy them seemlessly on AWS, GCP
or Azure.

Although both Serverless Framework and Lithops use serverless functions, their objective is completely different:
Serverless Framework aims to provide an easy-to-use tool to develop applications related to web services, like HTTP APIs,
while Lithops aims to develop applications related to highly parallel scientific computation and Big Data processing.
