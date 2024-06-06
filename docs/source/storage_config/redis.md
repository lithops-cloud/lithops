# Redis

Lithops with Redis as storage backend.


## Installation

1. Install Redis backend dependencies:

```bash
python3 -m pip install lithops[redis]
```

2. Install Redis >= 5.

3. Secure your installation by setting a password in the redis configuration file.


## Configuration

Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: redis

    redis:
        host : <REDIS_HOST_IP>
        port : <REDIS_HOST_PORT>
        password: <REDIS_PASSWORD>
```

 
## Summary of configuration keys for Redis

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|redis | host | localhost |no | The host ip address where you installed the Redis server. |
|redis | port | 6379 |no | The port where the redis server is listening |
|redis | username | None |no | The username (if any)|
|redis | password | None |no | The password you set in the Redis configuration file (if any) |
|redis | db | 0 |no | Number of database to use |
|redis | ssl | False |no | Activate ssl connection |
|redis | ... | |no |  All the parameters set in this lithops `redis` config section are directly passed to a [`reds.Redis()`](https://redis-py.readthedocs.io/en/stable/index.html#redis.Redis) instance, so you can set all the same parameters if necessary. |
