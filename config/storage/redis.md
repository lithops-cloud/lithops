# Lithops on Redis

Lithops with Redis as storage backend.


### Installation

1. Install Redis >= 5.

2. Secure your installation by setting a password in the redis configuraion file.


### Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: redis
        storage_bucket: storage

    redis:
        host : <REDIS_HOST_IP>
        port : <REDIS_HOST_PORT>
        password: <REDIS_PASSWORD>
```

- `host`: The host ip adress where you installed the Redis server.
- `port`: The port where the redis server is listening (default: 6379)
- `password`: The password you set in the Redis configuration file
 
