# Configuration keys

Summary of configuration keys:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|pywren|storage_bucket||yes|Any bucket that exists in your COS account. This will be used by PyWren for intermediate data |
|pywren|storage_prefix|pywren.jobs|no|Storage prefix is a virtual sub-directory in the bucket, to provide better control over location where PyWren writes temporary data. The COS location will be `storage_bucket/storage_prefix` |
|pywren|data_cleaner|False|no|If set to True, then cleaner will automatically delete temporary data that was written into `storage_bucket/storage_prefix`|
|pywren | storage_backend| ibm_cos | no | backend storage implementation. IBM COS is the default |
|pywren | invocation_retry| True | no | Retry invocation in case of failure |
|pywren | retry_sleeps | [1, 5, 10, 20, 30] | no | Number of seconds to wait before retry |
|pywren| retries | 5 | no | number of retries |
|ibm_cf| endpoint | | yes | IBM Cloud Functions hostname. Endpoint is the value of 'host' from [api-key](https://console.bluemix.net/openwhisk/learn/api-key). Make sure to use https:// prefix |
|ibm_cf| namespace | | yes | IBM Cloud Functions namespace. Value of CURRENT NAMESPACE from [api-key](https://console.bluemix.net/openwhisk/learn/api-key) |
|ibm_cf| api_key | | yes | IBM Cloud Functions api key. Value of api key from [api-key](https://console.bluemix.net/openwhisk/learn/api-key) |
|ibm_cf| action_timeout | 600000 |no |  Default timeout |
|ibm_cf| action_memory | 512 | no | Default memory |
|ibm_cos | endpoint | | yes | Endpoint to your COS account. Make sure to use full path. for example https://s3-api.us-geo.objectstorage.softlayer.net |
|ibm_cos | api_key | | yes | API Key to your COS account|
|ibm_cos | `ibm_auth_endpoint` | https://iam.cloud.ibm.com | no | Optional URL for IBM Authentication IAM |

#####  Using in-memory storage for temporary data

You can configure PyWren to use in-memory storage to keep the temporary data. We support currently [CloudAMQP](https://console.bluemix.net/catalog/services/cloudamqp) and more other services will be supported at later stage. To enable PyWren to use this service please setup additional key

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| rabbitmq |amqp_url | |no | Value of AMQP URL from the Management dashboard of CloudAMQP service |

In addition, activate service by

	pw = pywren.ibm_cf_executor(use_rabbitmq=True)

