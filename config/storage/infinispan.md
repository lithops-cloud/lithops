# Lithops on Infinispan

Lithops with Infinispan as storage backend.


### Installation

1. Install Infinispan.


### Configuration

2. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage_backend: infinispan

    infinispan:
        username   : <USER_NAME>
        password   : <PASSWORD>
        endpoint   : <INFINISPAN_SERVER_URL:PORT>
        cache_manager : <CACHE MANAGER>
```

- `username`: The username
- `password`: The password
- `endpoint`: The endpoint
- `cache_manager`: cahce manager. # Optional 'default' in default value
 
