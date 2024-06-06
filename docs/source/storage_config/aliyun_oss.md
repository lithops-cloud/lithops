# Aliyun Object Storage Service

Lithops with Aliyun Object Storage Service as storage backend.


## Installation

1. Install Alibaba Cloud backend dependencies:

```bash
python3 -m pip install lithops[aliyun]
```

## Configuration

1. [Navigate to the Cloud Console](https://ram.console.aliyun.com/manage/ak) and create a new AccessKey (If you don't have one)

2. Edit your lithops config and add the following keys:

```yaml
lithops:
    storage: aliyun_oss

aliyun:
    account_id: <ACCOUNT_ID>
    access_key_id: <ACCESS_KEY_ID>
    access_key_secret: <ACCESS_KEY_SECRET>
    region : <REGION_NAME>
```

## Summary of configuration keys for Aliyun

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun | account_id | |yes |  Alibaba Cloud Account ID |
|aliyun | access_key_id | |yes |  Access Key Id |
|aliyun | access_key_secret | |yes | Access Key Secret |
|aliyun | region | |yes | Region name. For example: `eu-west-1` |

## Summary of configuration keys for Aliyun Object Storage Service:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun_oss | region | | no | Region Name from [here](https://www.alibabacloud.com/help/en/object-storage-service/latest/regions-and-endpoints). Omit the `oss-` prefix. For example: `eu-west-1`. Lithops will use the region set under the `aliyun` section if it is not set here |
|aliyun_oss | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided|