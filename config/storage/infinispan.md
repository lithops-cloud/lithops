# Lithops on Infinispan

Lithops with Infinispan as storage backend.


### Installation

1. Install Infinispan.


### Configuration

2. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: infinispan
        storage_bucket: storage

    infinispan:
        username   : <USER_NAME>
        password   : <PASSWORD>
        endpoint   : <INFINISPAN_SERVER_URL:PORT>
```

- `username`: The username
- `password`: The password
- `endpoint`: The endpoint
- `cache_name`: cahce name. # Optional 'default' in default value
- `cache_type`: Type of the cache. # Optional 'default' in default value
 
