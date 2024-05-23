# MinIO

Lithops with MinIO storage backend.


## Installation

1. Install MinIO backend dependencies:

```bash
python3 -m pip install lithops[minio]
```

2. Install MinIO.

3. Create a new user.

## Configuration

Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: minio

    minio:
        endpoint: <ENDPOINT_URL>
        access_key_id: <ACCESS_KEY>
        secret_access_key: <SECRET_ACCESS_KEY>
```

## Summary of configuration keys for MinIO

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|minio | endpoint | |yes | The host ip adress where you installed the Ceph server. Must start with http:// or https:// |
|minio | access_key_id | |yes | Account user access key |
|minio | secret_access_key | |yes | Account user secret access key |
|minio | session_token | |no | Session token for temporary AWS credentials |
|minio | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |