Prometheus Monitoring
=====================

.. warning:: This feature is experimental and as such is unstable. Using it in production is discouraged. Expect errors and API/functionality changes in future releases.

Lithops allows to send executions metrics to Prometheus for real-time monitoring purposes.
Currently this feature works by using a Prometheus apigateway.

Installation
------------

For testing purposes, the easiest way to get everything up is to use an Ubuntu VM and install the pre-compiled packages from the *apt* repository

1. Install the Prometheus severer:

.. code::

    apt-get update
    apt-get install prometheus -y

2. Install Prometheus Pushgateway module:

.. code::

    apt-get install prometheus-pushgateway -y

Configuration
-------------

Edit your config and enable the monitoring system by including the *telemetry* key in the lithops section:

.. code:: yaml

    lithops:
        telemetry: true

Add in your config a new section called *prometheus* with the following keys:

.. code:: yaml

    prometheus:
        apigateway: <http://apigateway_ip:port>


.. list-table::
   :header-rows: 1

   * - Group
     - Key
     - Default
     - Optional
     - Additional Info
   * - prometheus
     - apigateway
     - ``None``
     - No
     - Prometheus apigateway endpointt. Make sure to use http:// prefix and corresponding port. For example: http://localhost:9091
