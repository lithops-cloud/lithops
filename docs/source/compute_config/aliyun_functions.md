# Aliyun Function Compute

Lithops with *Aliyun Function Compute* as serverless compute backend.

## Installation

1. Install Alibaba Cloud backend dependencies:

```
$ python3 -m pip install lithops[aliyun]
```

1. Access to your [console](https://homenew-intl.console.aliyun.com/) and activate your Functions service instance.

## Configuration

1. [Access to your Function Compute dashboard](https://fc.console.aliyun.com/fc/overview), choose your preferred region, and copy the public endpoint.

2. Access to the [Resource Access Management (RAM) Roles dashboard](https://ram.console.aliyun.com/roles/), and create a new Role that contains the `AliyunOSSFullAccess` permission. Alternatively you can use an already created Role that contains the `AliyunOSSFullAccess` permission.


3. Edit your Lithops config and add the following keys:

```yaml
  lithops:
      backend : aliyun_fc

  aliyun:
    access_key_id: <ACCESS_KEY_ID>
    access_key_secret: <ACCESS_KEY_SECRET>

  aliyun_fc:
      public_endpoint : <PUBLIC_ENDPOINT>
      role_arn: <ROLE_ARN>
```

4. **(optional)** By default Lithops will automatically create a new **service** in your *Function Compute* account. For this purpose your user must have **List** and **Create** permissions to *Function Compute*. Alternatively, you can create a new service through the dashboard (or use one already created), assign the Role created in the previous step (Accessing to *service configuration* --> *Modify Configuration* --> *Role Config*), and configure the *service* entry in the *aliyun_cf* config section.


## Summary of configuration keys for Aliyun

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun | access_key_id | |yes |  Access Key Id |
|aliyun | access_key_secret | |yes | Access Key Secret |

    
## Summary of configuration keys for Alibaba Functions Compute:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun_fc | public_endpoint | |yes | public endpoint (URL) to the service. OSS and FC endpoints are different. |
|aliyun_fc | role_arn | |yes | Role ARN. For example: `acs:ram::5244532493961771:role/aliyunfclogexecutionrole` |
|aliyun_fc | service | |no | Service name |
|aliyun_fc | max_workers | 300 | no | Max number of workers per `FunctionExecutor()`|
|aliyun_fc | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|aliyun_fc | runtime |  |no | Docker image name.|
|aliyun_fc | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|aliyun_fc | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|aliyun_fc | invoke_pool_threads | 300 |no | Number of concurrent threads used for invocation |