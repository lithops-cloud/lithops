# MinIO

Lithops with MinIO storage backend.


## Installation

1. Install MinIO.

2. Create a new user.

3. Create a new bucket (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: minio

    minio:
        storage_bucket: <BUCKET_NAME>
        endpoint: <ENDPOINT_URL>
        access_key_id: <ACCESS_KEY>
        secret_access_key: <SECRET_ACCESS_KEY>
```

## Summary of configuration keys for MinIO

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|minio | storage_bucket | | yes | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in `lithops` section |
|minio | endpoint | |yes | The host ip adress where you installed the Ceph server. Must start with http:// or https:// |
|minio | access_key_id | |yes | Account user access key |
|minio | secret_access_key | |yes | Account user secret access key |
