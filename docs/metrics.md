#Prometheus Monitoring (Experimental)

**!! NOTE: This is an experimental feature and everything related to it can change rapidly**

Lithops allows to send executions metrics to Prometheus for real-time monitoring purposes.
Currently this feature works by using a Prometheus apigateway.

## Installation

For testing purposes, the easiest way to get everything up is to use an Ubuntu VM and install the pre-compiled packages from the *apt* repository

1. Install the Prometheus severer:
```bash
# apt-get update
# apt-get install prometheus -y
```

2. Install Prometheus Pushgateway module:
```bash
# apt-get install prometheus-pushgateway -y
```

## Configuration
Edit your config and enable the monitoring system by including the *monitoring* key in the lithops section:
```yaml
lithops:
    monitoring: true
```

Add in your config a new section called *prometheus* with the following keys:

```yaml
prometheus:
    apigateway: <http://apigateway_ip:port>
```


|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|prometheus | apigateway | |yes | Prometheus apigateway endpointt. Make sure to use http:// prefix and corresponding port. For example: http://localhost:9091 |
