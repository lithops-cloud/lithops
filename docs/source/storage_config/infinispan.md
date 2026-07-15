# Infinispan

Lithops with Infinispan as storage backend. Infinispan provides two different endpoints: `infinispan` (REST) and
`infinispan_hotrod` (native binary).


## Installation

1. Install Infinispan.


## Configuration

Edit your Lithops config file and add the following keys:

### REST endpoint
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

#### Summary of configuration keys for Infinispan:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|infinispan | endpoint | |yes | Endpoint to your Infinispan server |
|infinispan | username | |yes | The username |
|infinispan | password | |yes | The password |
|infinispan | mech | |no | Authentication mechanism |
|infinispan | cache_names | | no | List of cache names. Each bucket will be mapped to a different cache with the same name. Defaults to `['storage']` |
|infinispan | cache_type | | no | Type of the cache. Defaults to `default` |


### Hotrod endpoint:

To run this endpoint you need to compile and install the Infinispan Python client ([home page](https://github.com/infinispan/python-client)).

```yaml
    lithops:
        storage: infinispan_hotrod
        data_limit: 8 # More space for data than the 4MB default

    infinispan_hotrod:
        username   : <USER_NAME>
        password   : <PASSWORD>
        endpoint   : <INFINISPAN_SERVER_HOSTNAME:PORT>
        cache_names :
        - cache_name_1
        - cache_name_2
        - ...
```

#### Summary of configuration keys for Infinispan_hotrod:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|infinispan_hotrod | endpoint | |yes | Endpoint to your Infinispan server |
|infinispan_hotrod | username | |yes | The username |
|infinispan_hotrod | password | |yes | The password |
|infinispan_hotrod | cache_names | | no | List of cache names. Each bucket will be mapped to a different cache with the same name. Defaults to `['storage']` |

