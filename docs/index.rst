.. Lithops documentation master file, created by
   sphinx-quickstart on Tue Jul 27 19:17:14 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Lithops: Lightweight Optimized Processing
=========================================

Lithops is a Python multi-cloud distributed computing framework. It allows to run unmodified local python code at
massive scale in the main serverless computing platforms. Lithops delivers the user’s code into the cloud without
requiring knowledge of how it is deployed and run. Moreover, its multicloud-agnostic architecture ensures portability
across cloud providers, overcoming vendor lock-in.

Lithops provides value for a great variety of uses cases like big data analytics and embarrassingly parallel jobs. It is
specially suited for highly-parallel programs with little or no need for communication between processes, but it also
supports parallel applications that need to share state among processes. Examples of applications that run with Lithops
include Monte Carlo simulations, deep learning and machine learning processes, metabolomics computations, and geospatial
analytics, to name a few.


.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Lithops Core

   source/design.md
   source/supported_clouds.md

.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Lithops Futures API

   source/api_futures.md
   source/functions.md

.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Storage

   source/api_storage.md
   source/api_storage_os.md

.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Data Processing

   source/data_processing.md
   source/file_chunking.md

.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Execution Modes

   source/mode_localhost.md
   source/mode_serverless.md
   source/mode_standalone.md

.. toctree::
   :hidden:
   :maxdepth: -1
   :caption: Other

   source/api_multiprocessing.md
   source/dso.md
   source/sklearn_joblib.md
   source/metrics.md
   source/testing.md
