Customize Worker Granularity
============================

By default, Lithops worker granularity is et to 1. That is, each function activations is run in a different runtime instance.
You can change this by using the ``chunksize`` parameter of the map and map_reduce calls.

By default, Lithops uses one process in each runtime instance.
You can change this by using the ``worker_processes`` parameter in the configuration of your backend.
This parameter allows to start multiple processes within the same runtime instance. 
This is convenient if your runtime have access to more than one CPU.
