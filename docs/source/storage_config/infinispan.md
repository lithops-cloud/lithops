# Infinispan

Lithops with Infinispan as storage backend, over the Infinispan REST endpoint.


## Installation

1. Install Infinispan.


## Configuration

Edit your Lithops config file and add the following keys:

```yaml
    lithops:
        storage: infinispan
        data_limit: 8 # More space for data than the 4MB default

    infinispan:
        username   : <USER_NAME>
        password   : <PASSWORD>
        mech: <DIGEST|BASIC> # Defaults to DIGEST
        endpoint   : <INFINISPAN_SERVER_URL:PORT>
        cache_names :
        - cache_name_1
        - cache_name_2
        - ...
```

## Summary of configuration keys for Infinispan:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|infinispan | endpoint | |yes | Endpoint to your Infinispan server |
|infinispan | username | |yes | The username |
|infinispan | password | |yes | The password |
|infinispan | mech | DIGEST |no | Authentication mechanism: DIGEST or BASIC |
|infinispan | cache_names | | no | List of cache names. Each bucket will be mapped to a different cache with the same name. Defaults to `['storage']` |
|infinispan | cache_type | | no | Type of the cache. Defaults to `default` |
