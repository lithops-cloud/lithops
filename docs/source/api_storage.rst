Storage API Details
===================

Lithops lets you create a **Storage** instance that abstracts away the backend implementation details.
The standard way to set up a Storage object is to import the Lithops ``Storage`` class and create an instance.

By default, the configuration is loaded from the Lithops config file, so there is no need to provide any parameter
to create a Storage instance:

.. code:: python

    from lithops import Storage

    storage = Storage()

Alternatively, you can pass the Lithops configuration through a dictionary. In this case, it will load the storage
backend set in the ``storage`` key of the ``lithops`` section:

.. code:: python

    from lithops import Storage

    config = {'lithops': {'storage': 'ibm_cos'},
              'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'}}

    storage = Storage(config=config)

In case you have multiple storage backends set in your configuration, you can force a specific storage backend by
using the ``backend`` parameter:

.. code:: python

    from lithops import Storage

    storage = Storage(backend='redis')  # this will create a redis Storage instance

or:

.. code:: python

    from lithops import Storage

    config = {'lithops': {'storage': 'ibm_cos'},
              'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'},
              'redis': {'host': 'HOST', 'port': 'PORT'}}


    storage = Storage(config=config)  # this will create an ibm_cos Storage instance
    storage = Storage(config=config, backend='redis')  # this will create a redis Storage instance

Storage API Reference
---------------------

.. autoclass:: lithops.storage.storage.Storage
   :members:
   :undoc-members:
   :show-inheritance:
