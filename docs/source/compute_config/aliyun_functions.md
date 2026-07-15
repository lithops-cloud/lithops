# Aliyun Function Compute

Lithops with *Aliyun Function Compute* as serverless compute backend.

## Installation

1. Install Alibaba Cloud backend dependencies:

```bash
python3 -m pip install lithops[aliyun]
```

2. Access to your [console](https://homenew-intl.console.aliyun.com/) and activate your Functions service instance.

## Configuration

1. [Navigate to the Cloud Console](https://ram.console.aliyun.com/manage/ak) and create a new AccessKey (If you don't have one)

2. [Access to your Function Compute dashboard](https://fc.console.aliyun.com/fc/overview), and choose your preferred region.

3. Access the [Resource Access Management (RAM) Roles dashboard](https://ram.console.aliyun.com/roles/), and create a new Role that contains the `AliyunOSSFullAccess` permission. Alternatively you can use an already created Role that contains the `AliyunOSSFullAccess` permission.

4. Edit your Lithops config and add the following keys:

```yaml
lithops:
    backend : aliyun_fc

aliyun:
    account_id: <ACCOUNT_ID>
    access_key_id: <ACCESS_KEY_ID>
    access_key_secret: <ACCESS_KEY_SECRET>
    region : <REGION_NAME>

aliyun_fc:
    role_arn: <ROLE_ARN>
```

5. Your RAM user needs permissions to create, list, invoke, and delete **FC 3.0 functions** (for example `AliyunFCFullAccess`). The `role_arn` is attached to each Lithops worker function so it can access OSS and other services.


## Summary of configuration keys for Aliyun

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun | account_id | |yes |  Alibaba Cloud Account ID |
|aliyun | access_key_id | |yes |  Access Key Id |
|aliyun | access_key_secret | |yes | Access Key Secret |
|aliyun | region | |yes | Region name. For example: `eu-west-1` |

    
## Summary of configuration keys for Alibaba Functions Compute:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun_fc | role_arn | |yes | Role ARN. For example: `acs:ram::5244532493961771:role/aliyunfclogexecutionrole` |
|aliyun_fc | region | |no | Region name. For example: `us-east-1`. Lithops will use the region set under the `aliyun` section if it is not set here |
|aliyun_fc | max_workers | 300 | no | Max number of workers. Alibaba limits the number of parallel workers to 300|
|aliyun_fc | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|aliyun_fc | runtime |  |no | Runtime name you built and deployed using the lithops client|
|aliyun_fc | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|aliyun_fc | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|aliyun_fc | invoke_pool_threads | 300 |no | Number of concurrent threads used for invocation |
|aliyun_fc | deploy_mode | runtime | no | `runtime` (zip + managed Python) or `custom-container` (Docker image) |
|aliyun_fc | docker_server | docker.io | no | Container registry host (Docker Hub by default) |
|aliyun_fc | docker_user | | no | Docker Hub user/namespace; **required** for `custom-container` |
|aliyun_fc | docker_password | | no | Registry password or token used when pushing images |


## Test Lithops
Once you have your compute and storage backends configured, you can run a Hello World function with:

```bash
lithops hello -b aliyun_fc -s aliyun_oss
```


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```