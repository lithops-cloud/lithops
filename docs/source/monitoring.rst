Monitoring
==========

By default, Lithops uses the storage backend to monitor function activations: each function activation stores a file
named *{id}/status.json* in Object Storage when it finishes its execution. This file contains statistics about the
execution, including whether the function activation ran successfully or not. Based on these files, the default
monitoring approach polls the Object Storage every few seconds to determine which function activations have finished
and which have not.

Since this default approach can slow down total application execution time due to the number of requests it has to
make against the object storage, Lithops also integrates a RabbitMQ service to monitor function activations in real time.
With RabbitMQ, the content of the *{id}/status.json* file is sent through a queue. This speeds up total application
execution time since Lithops only needs one connection to the messaging service to monitor all function activations.
We currently support the AMQP protocol.

.. note:: The RabbitMQ server has to be accessible from both the client and the functions. For example, it could be deployed in a cloud server with a public IP address and with the AMQP port open (5672).

To enable Lithops to use this service, add the *AMQP_URL* key into the *rabbitmq* section in
the configuration, for example:

.. code:: yaml

    rabbitmq:
        amqp_url: <AMQP_URL>  # amqp://

In addition, activate the monitoring service by setting ``monitoring: rabbitmq`` in the configuration (Lithops section):

.. code:: yaml

    lithops:
       monitoring: rabbitmq


.. code:: python

    fexec = lithops.FunctionExecutor(monitoring='rabbitmq')