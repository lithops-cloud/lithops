# Aliyun Object Storage Service

Lithops with Aliyun Object Storage Service as storage backend.


## Configuration

1. Install Alibaba Cloud backend dependencies:

```
$ python3 -m pip install lithops[aliyun]
```

2. [Navigate to the Cloud Console](https://ram.console.aliyun.com/manage/ak) and create a new AccessKey (If you don't have one)


## Configuration

1. Navigate to your storage account and create a new bucket (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

2. Edit your lithops config and add the following keys:

```yaml
  lithops:
    storage: aliyun_oss

  aliyun:
    access_key_id: <ACCESS_KEY_ID>
    access_key_secret: <ACCESS_KEY_SECRET>

  aliyun_oss:
    storage_bucket: <BUCKET_NAME>
    public_endpoint: <PUBLIC_ENDPOINT>
    internal_endpoint: <INTRANET_ENDPOINT>
```

## Summary of configuration keys for Aliyun

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun | access_key_id | |yes |  Access Key Id |
|aliyun | access_key_secret | |yes | Access Key Secret |

## Summary of configuration keys for Aliyun Object Storage Service:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun_oss | storage_bucket | | yes | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data.|
|aliyun_oss | public_endpoint | |yes | public endpoint (URL) to the service. OSS and FC endpoints are different |
|aliyun_oss | internal_endpoint | | yes | internal endpoint (URL) to the service. Provides cost-free inbound and outbound traffic among services from the same intranet (region)|