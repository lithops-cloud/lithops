# Ceph

Lithops with Ceph storage backend.


## Installation

1. Install Ceph backend dependencies:

```bash
python3 -m pip install lithops[ceph]
```

2. Install Ceph.

3. Create a new user.


## Configuration

1. Edit your lithops config file and add the following keys:

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
|ceph | endpoint | |yes | The host ip address where you installed the Ceph server. Must start with http:// or https:// |
|ceph | region | |no | Region name. For example 'eu-west-1'  |
|ceph | access_key_id | |yes | Account user access key |
|ceph | secret_access_key | |yes | Account user secret access key |
|ceph | session_token | |no | Session token for temporary AWS credentials |
|ceph | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |
