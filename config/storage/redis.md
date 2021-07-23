# Lithops on Redis

Lithops with Redis as storage backend.


### Installation

1. Install Redis >= 5.

2. Secure your installation by setting a password in the redis configuration file.


### Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: redis

    redis:
        host : <REDIS_HOST_IP>
        port : <REDIS_HOST_PORT>
        password: <REDIS_PASSWORD>
```

 
#### Summary of configuration keys for Redis:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|redis | host | |yes | The host ip adress where you installed the Redis server. |
|redis | port | |no | The port where the redis server is listening (default: 6379) |
|redis | password | |no | The password you set in the Redis configuration file (if any) |
