Monitoring
==========

While a job runs, the client has to know which of its function activations have started, which have finished, and
whether each one succeeded. Lithops calls this *monitoring*, and it is what makes ``wait()``, ``get_result()`` and the
progress bar work.

Monitoring is a *channel*, not a storage provider: it only decides how call statuses travel back to the client. Your
compute and storage backends are unaffected by the choice, and so are your results.


How it works
------------

Every activation reports twice: once when it starts, and once when it finishes. The final report carries the execution
statistics and whether the call raised an exception.

Lithops can carry those reports in two ways.

**Storage polling** (the default). Each activation writes its status into the storage backend the executor already
uses, under a key of its own:

.. code::

    lithops.jobs/<executor_id>-<job_id>/<call_id>/<activation_id>.init   # the call started
    lithops.jobs/<executor_id>-<job_id>/<call_id>/status.json            # the call finished

The client lists those keys every couple of seconds to work out what has happened. It needs no extra infrastructure,
which is why it is the default. The cost is that a job with many activations means many requests against the object
storage, and a status is only noticed on the next poll.

**Message services.** The same status is published to a queue or a topic instead. The client holds one connection and
is notified as each message arrives, so a status shows up as soon as it is sent and the number of activations does not
change how much the client has to ask for.

.. note::
    A message service has to be reachable **from both the client and the functions**. This is the usual reason a
    message backend works locally but not in the cloud, or the other way around.


Which one to use
----------------

.. list-table::
   :header-rows: 1
   :widths: 18 34 22 26

   * - ``monitoring``
     - What it needs
     - Extra dependency
     - Created per executor
   * - ``storage``
     - nothing, reuses your storage backend
     - none
     - nothing
   * - ``rabbitmq``
     - a RabbitMQ broker
     - none
     - one queue
   * - ``redis``
     - a Redis server
     - ``lithops[redis]``
     - one list
   * - ``aws_sqs``
     - an AWS account
     - ``lithops[aws]``
     - one queue
   * - ``gcp_pubsub``
     - a GCP project
     - ``lithops[gcp]``
     - one topic and subscription
   * - ``azure_queue``
     - an Azure storage account
     - ``lithops[azure]``
     - one queue

**Start with** ``storage``. It works everywhere and needs nothing set up. Move to a message backend when one of these
actually shows up in your timings: jobs of many thousands of activations, where the storage requests add up; or short
functions, where waiting for the next poll is a noticeable part of the total.

If you already run one of these services for something else, using it here costs you nothing extra.


What to expect
--------------

**Your results are never at risk.** Whichever backend is configured, the final status of every call is also written to
the object storage. If a message is lost, Lithops notices and reads the status back from there, so the job still
finishes normally. A message backend is a faster path for the same information, not a different source of truth.

**Resources are cleaned up on exit.** A message backend creates one queue, topic or list per executor, named after the
executor id. It is created before the first function is invoked and deleted when the executor shuts down — when the
``with`` block ends, or on interpreter exit. A process killed hard enough to skip that leaves the resource behind, and
it has to be removed by hand.

**Nested executors work.** A function may create a ``FunctionExecutor`` of its own. Its call statuses reach every
executor up the chain, so a client waiting on the outer job still sees the progress of the inner one.

**A worker retries.** If publishing a status fails, the worker tries again a few times, backing off, before giving up
and logging an error. The status is still in the object storage either way.


Configuration
-------------

Select the backend in the ``lithops`` section of your config file:

.. code:: yaml

    lithops:
        monitoring: storage          # storage | rabbitmq | redis | aws_sqs | gcp_pubsub | azure_queue

or per executor:

.. code:: python

    fexec = lithops.FunctionExecutor(monitoring='rabbitmq')

``monitoring_interval`` sets how often the client polls, in seconds. It is used **only by the** ``storage`` **backend**;
message backends are event-driven and ignore it.

.. code:: yaml

    lithops:
        monitoring_interval: 2

.. note::
    The default is ``2``, except with the localhost storage backend, where it is ``0.1`` because polling a local
    directory is cheap.

Each backend then reads its own section. Where a matching cloud provider section already exists, it is used as the
default, so you rarely have to repeat credentials.


RabbitMQ
~~~~~~~~

.. code:: yaml

    lithops:
        monitoring: rabbitmq

    rabbitmq:
        amqp_url: <AMQP_URL>  # amqp://<USER>:<PASSWORD>@<HOST>:<PORT>/<VHOST>

``amqp_url`` is mandatory. The broker has to be reachable from your functions as well as from the client — for
instance a cloud server with a public IP and the AMQP port (5672) open.

The same section is used by the Kubernetes backend with ``rabbitmq_executor: True`` and by the Singularity backend.


Redis
~~~~~

.. code:: yaml

    lithops:
        monitoring: redis

    redis:
        host: <REDIS_HOST>
        #port: 6379
        #username: <USERNAME>
        #password: <PASSWORD>

``host`` is mandatory. This is the same section as the Redis storage backend, so a deployment that already stores data
in Redis needs no new keys.


AWS SQS
~~~~~~~

.. code:: yaml

    lithops:
        monitoring: aws_sqs

    aws:
        region: <REGION>
        #access_key_id: <ACCESS_KEY_ID>
        #secret_access_key: <SECRET_ACCESS_KEY>

``region`` is mandatory. Credentials may instead come from the environment or an instance role. Add an ``aws_sqs``
section only if you need to override what is in ``aws``.


GCP Pub/Sub
~~~~~~~~~~~

.. code:: yaml

    lithops:
        monitoring: gcp_pubsub

    gcp:
        project_name: <GCP_PROJECT_ID>
        #credentials_path: <ABSOLUTE_PATH_TO_SERVICE_ACCOUNT_JSON>

``project_name`` is mandatory, but it is read from the service account JSON when a credentials file is given.
``credentials_path`` falls back to ``GOOGLE_APPLICATION_CREDENTIALS``. Add a ``gcp_pubsub`` section only if you need to
override what is in ``gcp``.


Azure Queue Storage
~~~~~~~~~~~~~~~~~~~

.. code:: yaml

    lithops:
        monitoring: azure_queue

    azure_storage:
        storage_account_name: <STORAGE_ACCOUNT>
        storage_account_key: <STORAGE_ACCOUNT_KEY>

Both keys are mandatory. Add an ``azure_queue`` section only if you need to override what is in ``azure_storage``.
Azure only accepts lowercase queue names, so Lithops adjusts the name it derives from the executor id.
