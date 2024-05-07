# Ceph

Lithops with Ceph storage backend.


## Installation

1. Install Ceph backend dependencies:

```bash
python3 -m pip install lithops[ceph]
```

2. Install Ceph.

3. Create a new user.

4. Create a new bucket (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: ceph

    ceph:
        endpoint: <ENDPOINT_URL>
        access_key_id: <ACCESS_KEY>
        secret_access_key: <SECRET_ACCESS_KEY>
```

 
## Summary of configuration keys for Ceph:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ceph | endpoint | |yes | The host ip adress where you installed the Ceph server. Must start with http:// or https:// |
|ceph | access_key_id | |yes | Account user access key |
|ceph | secret_access_key | |yes | Account user secret access key |
|ceph | session_token | |no | Session token for temporary AWS credentials |
|ceph | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |
