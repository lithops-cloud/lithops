# Configuration keys

Summary of configuration keys for IBM-PyWren:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|pywren|storage_bucket||yes|Any bucket that exists in your COS account. This will be used by PyWren for intermediate data |
|pywren|storage_prefix|pywren.jobs|no|Storage prefix is a virtual sub-directory in the bucket, to provide better control over location where PyWren writes temporary data. The COS location will be `storage_bucket/storage_prefix` |
|pywren|data_cleaner|False|no|If set to True, then cleaner will automatically delete temporary data that was written into `storage_bucket/storage_prefix`|
|pywren | storage_backend| ibm_cos | no | backend storage implementation. IBM COS is the default |
|pywren | invocation_retry| True | no | Retry invocation in case of failure |
|pywren | retry_sleeps | [1, 5, 10, 15, 20] | no | Number of seconds to wait before retry |
|pywren| retries | 5 | no | number of retries |
|pywren| runtime_timeout | 600000 |no |  Default timeout |
|pywren| runtime_memory | 256 | no | Default memory |


Summary of configuration keys for IBM Cloud Functions:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cf| endpoint | | yes | IBM Cloud Functions hostname. Endpoint is the value of 'HOST' from [api-key](https://cloud.ibm.com/openwhisk/learn/api-key). Make sure to use https:// prefix |
|ibm_cf| namespace | | yes | IBM Cloud Functions namespace. Value of CURRENT NAMESPACE from [api-key](https://cloud.ibm.com/openwhisk/learn/api-key) |
|ibm_cf| api_key | | yes | IBM Cloud Functions api key. Value of 'KEY' from [api-key](https://console.bluemix.net/openwhisk/learn/api-key) |


Summary of configuration keys for IBM Cloud Object Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cos | endpoint | | yes | Regional endpoint to your COS account. Make sure to use full path. For example https://s3.us-east.cloud-object-storage.appdomain.cloud |
|ibm_cos | private_endpoint | | no | Private regional endpoint to your COS account. Make sure to use full path. For example: https://s3.private.us-east.cloud-object-storage.appdomain.cloud |
|ibm_cos | api_key | | yes | API Key to your COS account|

Summary of configuration keys for IBM IAM authentication

When using IAM authentication one IAM key can be used to authenticate against IBM COS and IBM Cloud Functions. In this case, setup IAM key in the 

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_iam | iam_key | | no | IBM key to authenticate against IBM COS and IBM Cloud Functions
|ibm_iam |`ibm_auth_endpoint`| https://iam.cloud.ibm.com/oidc/token | no | Optional URL for IBM Authentication IAM |


### Using in-memory storage for monitoring function executions

You can configure PyWren to use in-memory storage to monitor function executions in real time. We support currently [CloudAMQP](https://cloud.ibm.com/catalog/services/cloudamqp) and more other services will be supported at later stage. To enable PyWren to use this service please setup additional key.

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| rabbitmq |amqp_url | |no | Value of AMQP URL from the Management dashboard of CloudAMQP service |

In addition, activate service by

	pw = pywren.ibm_cf_executor(rabbitmq_monitor=True)

