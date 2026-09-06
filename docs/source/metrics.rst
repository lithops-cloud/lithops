Metrics and Telemetry
=====================

Lithops already measures a great deal about every call it runs: how long the
function took, how long it waited to be scheduled, how much memory and CPU the
worker used, how much data it moved, whether the worker was cold, and how big
the result was. All of it comes back with the call status, and until the job
ends it lives only in the client process.

Telemetry turns those numbers into metrics, so a job can be watched while it
runs and compared against every job that ran before it.

.. code:: yaml

    lithops:
        telemetry: prometheus


How it works
------------

Metrics are produced entirely on the **client**. The worker writes its status
exactly as it always did; the monitor thread that reads the status feeds the
numbers into the exporter on its way past, and a background thread pushes what
has been aggregated every ``telemetry_interval`` seconds.

Nothing is added to the critical path of a function, no worker needs a route to
the metrics system, and every monitoring backend — ``storage``, ``rabbitmq``,
``redis``, ``aws_sqs``, ``gcp_pubsub``, ``azure_queue`` — is instrumented by the
same code.

Two backends ship with Lithops:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Backend
     - Use it when
   * - ``prometheus``
     - There is a Prometheus Pushgateway, or you would rather not add the
       OpenTelemetry SDK to the client. Lithops pushes to the gateway, which
       Prometheus then scrapes. One small pure-Python dependency.
   * - ``otlp``
     - Everything else, including Prometheus. Lithops exports over OTLP, which
       Prometheus can receive directly, an OpenTelemetry collector can forward
       to Prometheus over remote write, and a hosted service can take as it
       is. No Pushgateway, and none of the caveats that come with one.

Both backends export the same metric names, so a dashboard written against one
works against the other, and switching is a one-line configuration change.

Install the dependencies with:

.. code::

    pip install lithops[telemetry]


Enabling it
-----------

``telemetry`` names the backend. ``true`` is accepted and selects
``prometheus``; the default is ``false``, and while telemetry is off the client
library of a backend is never even imported.

.. list-table::
   :header-rows: 1
   :widths: 15 20 15 50

   * - Group
     - Key
     - Default
     - Additional info
   * - lithops
     - telemetry
     - ``False``
     - Telemetry backend. One of ``False``, ``prometheus``, ``otlp``.
   * - lithops
     - telemetry_interval
     - ``10``
     - Seconds between pushes. Metrics are also pushed once when the executor
       is cleaned up and once when the process exits.


Prometheus
----------

Lithops is a client, not a server: it runs for as long as the job does, so
there is nothing for Prometheus to scrape. The Pushgateway exists for exactly
that. Lithops keeps a registry of cumulative metrics and replaces its
Pushgateway group with it on every push.

Installing Prometheus and the Pushgateway
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The quickest way to get all three services up, including Grafana:

.. code:: yaml

    # docker-compose.yml
    services:
      pushgateway:
        image: prom/pushgateway
        ports: ["9091:9091"]
      prometheus:
        image: prom/prometheus
        ports: ["9090:9090"]
        volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml"]
      grafana:
        image: grafana/grafana
        ports: ["3000:3000"]

.. code:: yaml

    # prometheus.yml
    global:
      scrape_interval: 15s
    scrape_configs:
      - job_name: pushgateway
        honor_labels: true          # keep the job/instance labels Lithops pushes
        static_configs:
          - targets: ["pushgateway:9091"]

``honor_labels: true`` matters: without it Prometheus overwrites the ``job``
and ``instance`` labels of everything the gateway serves with the identity of
the gateway itself.

Configuration
~~~~~~~~~~~~~

.. code:: yaml

    lithops:
        telemetry: prometheus

    prometheus:
        gateway: http://localhost:9091

.. list-table::
   :header-rows: 1
   :widths: 15 20 20 45

   * - Group
     - Key
     - Default
     - Additional info
   * - prometheus
     - gateway
     - ``http://localhost:9091``
     - Pushgateway base URL, with the scheme and the port.
   * - prometheus
     - job
     - ``lithops``
     - The ``job`` label of the pushed group.
   * - prometheus
     - instance
     - the hostname
     - The ``instance`` label of the pushed group. See the note below before
       changing it.
   * - prometheus
     - username
     - -
     - Basic auth user, when the gateway is behind one.
   * - prometheus
     - password
     - -
     - Basic auth password, when the gateway is behind one.
   * - prometheus
     - timeout
     - ``10``
     - Push timeout, in seconds.

.. note::

    A Pushgateway group never expires: it is served to Prometheus until
    something deletes it. ``instance`` therefore defaults to the hostname
    rather than to anything derived from the execution, so that a machine
    reuses one group for every job it ever runs instead of leaving one behind
    on every run. Set it explicitly only to something equally stable, and give
    two Lithops clients running concurrently on the same host two different
    values, or they will overwrite each other's group.


OpenTelemetry
-------------

.. code:: yaml

    lithops:
        telemetry: otlp

    otlp:
        endpoint: http://localhost:4318

Straight into Prometheus, without a collector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prometheus can receive OTLP itself, which means the ``otlp`` backend reaches it
with no collector and no Pushgateway in between. Start Prometheus with
``--web.enable-otlp-receiver`` and point Lithops at its OTLP path:

.. code:: yaml

    lithops:
        telemetry: otlp

    otlp:
        endpoint: http://localhost:9090/api/v1/otlp

This is the option to prefer for a new deployment. A Pushgateway group never
expires and has to be reasoned about; a push straight into Prometheus is
written to the TSDB and that is the end of it. The metric names Lithops
exports are already in Prometheus form, so they arrive unchanged.

Through a collector
~~~~~~~~~~~~~~~~~~~

The collector is worth the extra hop when Lithops is one workload among many,
or when the same metrics have to reach more than one destination:

.. code:: yaml

    # otel-collector-config.yaml
    receivers:
      otlp:
        protocols:
          http:
            endpoint: 0.0.0.0:4318
    exporters:
      prometheusremotewrite:
        endpoint: http://prometheus:9090/api/v1/write
    service:
      pipelines:
        metrics:
          receivers: [otlp]
          exporters: [prometheusremotewrite]

Prometheus needs ``--web.enable-remote-write-receiver`` for that endpoint.

.. list-table::
   :header-rows: 1
   :widths: 15 20 20 45

   * - Group
     - Key
     - Default
     - Additional info
   * - otlp
     - endpoint
     - ``http://localhost:4318``
     - Collector endpoint. For ``http/protobuf`` the ``/v1/metrics`` path is
       appended if it is not already there.
   * - otlp
     - protocol
     - ``http/protobuf``
     - One of ``http/protobuf``, ``grpc``. ``grpc`` additionally needs the
       ``opentelemetry-exporter-otlp-proto-grpc`` package.
   * - otlp
     - service_name
     - ``lithops``
     - The ``service.name`` resource attribute.
   * - otlp
     - instance
     - the hostname
     - The ``host.name`` resource attribute.
   * - otlp
     - headers
     - ``{}``
     - Extra headers, which is where the authentication of a hosted collector
       goes.
   * - otlp
     - timeout
     - ``10``
     - Export timeout, in seconds.


What is exported
----------------

Counters are exported without the ``_total`` suffix; Prometheus and
OpenTelemetry both add it themselves.

.. list-table::
   :header-rows: 1
   :widths: 42 12 46

   * - Metric
     - Type
     - What it measures
   * - ``lithops_jobs_submitted_total``
     - counter
     - Jobs handed to the compute backend.
   * - ``lithops_calls_invoked_total``
     - counter
     - Function calls handed to the compute backend.
   * - ``lithops_calls_started_total``
     - counter
     - Calls the client has seen start running.
   * - ``lithops_calls_completed_total``
     - counter
     - Calls that reached a final state, by ``outcome``: ``success``,
       ``failure``, ``timeout`` or ``chained``.
   * - ``lithops_cold_starts_total``
     - counter
     - Calls that ran in a cold worker.
   * - ``lithops_worker_cpu_seconds_total``
     - counter
     - CPU time consumed by the function, by ``mode``: ``user`` or ``system``.
   * - ``lithops_worker_network_bytes_total``
     - counter
     - Network traffic of the function, by ``direction``: ``sent`` or ``recv``.
   * - ``lithops_call_duration_seconds``
     - histogram
     - Wall clock time spent inside the user function.
   * - ``lithops_call_total_duration_seconds``
     - histogram
     - Wall clock time the worker spent on the call, Lithops overhead included.
   * - ``lithops_call_queue_delay_seconds``
     - histogram
     - Submission to worker start. The scheduling latency of the backend.
   * - ``lithops_call_worker_setup_seconds``
     - histogram
     - Worker start to the user function starting: unpacking the job,
       importing the modules, fetching the data.
   * - ``lithops_call_worker_teardown_seconds``
     - histogram
     - User function returning to the worker finishing: writing the result and
       reporting the status.
   * - ``lithops_call_status_latency_seconds``
     - histogram
     - Worker finish to client notice. The latency of the monitoring channel.
   * - ``lithops_call_result_download_seconds``
     - histogram
     - Client notice to the client holding the result, by ``source``:
       ``inline`` (the result travelled in the call status, no request needed)
       or ``storage`` (it had to be fetched).
   * - ``lithops_call_result_queries``
     - histogram
     - Storage requests the client made to get one result. Zero for an inline
       result.
   * - ``lithops_call_end_to_end_seconds``
     - histogram
     - Submission to the result in hand. The number the user actually feels —
       every other timing above is a slice of this one.
   * - ``lithops_call_result_size_bytes``
     - histogram
     - Size of the value the function returned.
   * - ``lithops_call_result_upload_seconds``
     - histogram
     - Time the worker spent writing the result to storage. Zero for a result
       small enough to travel in the call status.
   * - ``lithops_call_status_queries``
     - histogram
     - Storage requests the client made to learn the status of one call — what
       the monitoring channel costs against storage. Zero for the channels
       that push.
   * - ``lithops_worker_memory_bytes``
     - histogram
     - Memory of the worker, by ``kind``: ``peak``, ``baseline``, ``rss``,
       ``vms``, ``uss``. See the note below.
   * - ``lithops_worker_memory_utilization_ratio``
     - histogram
     - Memory over the memory the runtime was configured with, by ``kind``:
       ``peak`` or ``rss``.
   * - ``lithops_worker_cpu_utilization_percent``
     - histogram
     - CPU utilisation of the worker while the function ran.
   * - ``lithops_worker_info``
     - gauge
     - Always 1. Carries ``python_version`` and ``lithops_version`` as labels,
       alongside ``backend``, ``runtime_name`` and ``runtime_memory``.
   * - ``lithops_job_calls``
     - histogram
     - How many calls a job is made of.
   * - ``lithops_job_create_seconds``
     - histogram
     - Everything the client did before the first worker was invoked.
   * - ``lithops_job_serialize_seconds``
     - histogram
     - Of that, the time spent serialising the function and its data.
   * - ``lithops_job_partition_seconds``
     - histogram
     - Of that, the time spent partitioning the input, for a job that
       processes objects.
   * - ``lithops_job_upload_seconds``
     - histogram
     - Of that, the time spent uploading, by ``part``: ``function`` or
       ``data``. Zero for a function already in the cache.
   * - ``lithops_job_payload_bytes``
     - histogram
     - Size of what the client uploaded, by ``part``: ``function`` or ``data``.

.. note::

    The five kinds of ``lithops_worker_memory_bytes`` answer different
    questions, and it is worth knowing which one to look at.

    ``peak`` is the high water mark of the whole task, taken from
    ``getrusage``, and it is the number an out-of-memory kill is measured
    against — this is the one to size a runtime by. ``baseline`` is that same
    mark taken before the function started, so it is what the runtime itself
    costs before any user code runs, and ``peak - baseline`` is what the
    function added. ``rss``, ``vms`` and ``uss`` are single samples taken as
    the function returns, useful for the shape of the memory but not for the
    ceiling. ``peak`` and ``baseline`` are absent on workers that are not Unix.

.. note::

    The timing metrics decompose one call end to end, so a stacked graph of
    them accounts for every second of ``lithops_call_end_to_end_seconds``::

        host_submit ──┬── queue_delay ──── the backend scheduling the call
                      │
        worker_start ─┼── worker_setup ─── unpack, import, fetch data
                      │
        func_start ───┼── duration ─────── the user function
                      │
        func_end ─────┼── worker_teardown ─ write the result, report
                      │
        worker_end ───┼── status_latency ── the monitoring channel
                      │
        status_done ──┼── result_download ─ fetching what it returned
                      │
        result_done ──┘

    ``lithops_call_total_duration_seconds`` is the worker's share of that
    (setup + duration + teardown), which is the part a FaaS backend bills for.
    ``result_download`` is only recorded for the calls whose result is actually
    read: a job whose results are never fetched has none.

Every metric carries the same four labels, plus the one its own dimension adds.
``lithops_worker_info`` is the exception: it deliberately leaves out
``function_name``, because it describes what a runtime *is* rather than what
ran on it.



.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Label
     - Value
   * - ``backend``
     - The compute backend the job ran on, e.g. ``aws_lambda``.
   * - ``runtime_name``
     - The runtime the job ran in.
   * - ``runtime_memory``
     - The memory the runtime was configured with, in MB.
   * - ``function_name``
     - The name of the function that was mapped.

.. note::

    There is deliberately no ``job_id``, ``call_id`` or ``activation_id``
    label. Every distinct combination of label values is a separate time
    series, and Lithops runs jobs of tens of thousands of calls: a per-call
    label would mean a series per call, kept for ever. The label set is
    therefore bounded by how many distinct functions and runtimes are executed,
    not by how much work is done — which is what lets a 100,000 call job be
    summarised by ``histogram_quantile`` in a single query.

    Per-call detail is not lost. It is in the call status, which the client
    keeps, and which ``fexec.plot()`` and ``fexec.job_summary()`` render.


Querying it
-----------

A few queries to build a dashboard from:

.. code::

    # p50 / p95 / p99 execution time
    histogram_quantile(0.95,
      sum by (le, function_name) (rate(lithops_call_duration_seconds_bucket[5m])))

    # Calls currently in flight
    sum(lithops_calls_invoked_total) - sum(lithops_calls_completed_total)

    # Failure rate
    sum(rate(lithops_calls_completed_total{outcome!="success"}[5m]))
      / sum(rate(lithops_calls_completed_total[5m]))

    # Cold start rate
    sum(rate(lithops_cold_starts_total[5m]))
      / sum(rate(lithops_calls_started_total[5m]))

    # Scheduling latency of the backend, p95
    histogram_quantile(0.95,
      sum by (le, backend) (rate(lithops_call_queue_delay_seconds_bucket[5m])))

    # Runtimes that are over-provisioned: p95 peak memory well under 1.
    # Use kind="peak" — summing across the kinds mixes two distributions
    histogram_quantile(0.95,
      sum by (le, runtime_name, runtime_memory)
        (rate(lithops_worker_memory_utilization_ratio_bucket{kind="peak"}[30m])))

    # What the runtime costs before any user code runs
    histogram_quantile(0.5,
      sum by (le, runtime_name)
        (rate(lithops_worker_memory_bytes_bucket{kind="baseline"}[30m])))

    # Client-side overhead per job: preparing and uploading
    histogram_quantile(0.95,
      sum by (le, function_name) (rate(lithops_job_create_seconds_bucket[30m])))

    # What the monitoring channel costs against the storage backend
    sum(rate(lithops_call_status_queries_sum[5m]))

    # End-to-end latency as the user feels it, p95
    histogram_quantile(0.95,
      sum by (le, function_name) (rate(lithops_call_end_to_end_seconds_bucket[5m])))

    # Where the time actually goes: one series per phase, stack them
    sum by (phase) (label_replace(rate(lithops_call_queue_delay_seconds_sum[5m]),
                                  "phase", "queue", "", "")
                 or label_replace(rate(lithops_call_worker_setup_seconds_sum[5m]),
                                  "phase", "setup", "", "")
                 or label_replace(rate(lithops_call_duration_seconds_sum[5m]),
                                  "phase", "function", "", "")
                 or label_replace(rate(lithops_call_worker_teardown_seconds_sum[5m]),
                                  "phase", "teardown", "", "")
                 or label_replace(rate(lithops_call_status_latency_seconds_sum[5m]),
                                  "phase", "status", "", "")
                 or label_replace(rate(lithops_call_result_download_seconds_sum[5m]),
                                  "phase", "download", "", ""))

    # How often a result was small enough to skip storage entirely
    sum(rate(lithops_call_result_download_seconds_count{source="inline"}[5m]))
      / sum(rate(lithops_call_result_download_seconds_count[5m]))

    # The execution environments in use, for an "environment" panel
    count by (runtime_name, runtime_memory, python_version, lithops_version) (
      lithops_worker_info)

    # GB-seconds, the cost proxy of a FaaS backend
    sum by (function_name) (
      rate(lithops_call_total_duration_seconds_sum[5m])
        * on() group_left() (lithops_calls_completed_total * 0 + 1))

Point Grafana at Prometheus as a datasource and these become panels directly.
The natural layout is a row of counters across the top (calls in flight,
completed, failure rate, cold start rate), a latency percentile graph and a
throughput graph below it, a memory utilisation heatmap under that, and a table
built from ``lithops_worker_info`` showing the runtimes in use.


Troubleshooting
---------------

**Nothing arrives.** Metrics are pushed every ``telemetry_interval`` seconds,
so a job that finishes in less than that is only visible after the push that
the executor makes on cleanup. Raise the log level to ``DEBUG``: the exporter
logs the backend it started with and every push it could not make.

**Metrics arrive but Prometheus shows the gateway's own labels.** Set
``honor_labels: true`` on the scrape config.

**Telemetry never breaks a job.** A metrics system that is misconfigured or
unreachable is logged and switched off, not raised. If telemetry seems to be
doing nothing at all, ``DEBUG`` will say why.
