# Lithops on Ceph

Lithops with Ceph storage backend.


### Installation

1. Install Ceph.

2. Create a new user.


### Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: ceph

    ceph:
        endpoint: <ENDPOINT_URL>
        access_key: <ACCESS_KEY>
        secret_key: <ACCESS_KEY>
```

- `endpoint`: The host ip adress where you installed the Redis server.
- `access_key`, `secret_key`: Access KEy and Secret key provided when you created the user
 
