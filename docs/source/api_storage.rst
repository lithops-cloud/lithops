Storage API Details
===================

Lithops allows to create a **Storage** instance and abstract away the backend implementation details.
The standard way to get a Storage object set up is to import the lithops ``Storage`` class and create an instance.

By default, the configuration is loaded from the lithops config file, so there is no need to provide any parameter
to create a Storage instance:

.. code:: python

    from lithops import Storage

    storage = Storage()

Alternatively, you can pass the lithops configuration through a dictionary. In this case, it will load the storage
backend set in the ``storage`` key of the ``lithops`` section:

.. code:: python

    from lithops import Storage

    config = {'lithops' : {'storage_config' : 'ibm_cos'},
              'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'}}

    storage = Storage(config=config)

In case you have multiple storage set in your configuration, you can force the storage backend by
using the ``backend`` parameter:

.. code:: python

    from lithops import Storage

    storage = Storage(backend='redis') # this will create a redis Storage instance

or:

.. code:: python

    from lithops import Storage

    config = {'lithops' : {'storage_config' : 'ibm_cos'},
              'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'},
              'redis': {'host': 'HOST', 'port':'PORT'}}


    storage = Storage(config=config)  # this will create an ibm_cos Storage instance
    storage = Storage(config=config, backend='redis')  # this will create a redis Storage instance

Storage API Reference
---------------------

.. autoclass:: lithops.storage.storage.Storage
   :members:
   :undoc-members:
   :show-inheritance:
