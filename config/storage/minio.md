# Lithops on MinIO

Lithops with MinIO storage backend.


### Installation

1. Install MinIO.

2. Create a new user.

3. Create a new bucket (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

### Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: minio
        storage_bucket: <BUCKET_NAME>

    minio:
        endpoint: <ENDPOINT_URL>
        access_key: <ACCESS_KEY>
        secret_key: <ACCESS_KEY>
```

- `endpoint`: The host ip adress where you installed the MinIO server. Must start with http:// or https://
- `access_key`, `secret_key`: Access Key and Secret key provided when you created the user
 
