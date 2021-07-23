# Lithops on Infinispan

Lithops with Infinispan as storage backend.


### Installation

1. Install Infinispan.


### Configuration

2. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: infinispan

    infinispan:
        username   : <USER_NAME>
        password   : <PASSWORD>
        endpoint   : <INFINISPAN_SERVER_URL:PORT>
```

 
#### Summary of configuration keys for Infinispan:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|infinispan | endpoint | |yes | Endpoint to your Infinispan server |
|infinispan | username | |yes | The username |
|infinispan | password | |yes | The password |
|infinispan | cache_name | | no | cahce name. # Optional 'default' in default value |
|infinispan | cache_type | | no | Type of the cache. # Optional 'default' in default value |
