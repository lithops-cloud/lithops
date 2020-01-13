# Configuration

To make PyWren running, you need to configure the access to the IBM Cloud Functions and IBM Cloud Object Storage services.

* Access details to IBM Cloud Functions can be obtained [here](https://cloud.ibm.com/openwhisk/namespace-settings). 
* Follow [these](cos-credentials.md) instructions to obtain the IBM Cloud Object Storage credentials.

Alternatively, instead of creating one different `api_key` for each service, you can use the IBM IAM service to authenticate yourself against both services. In this case, setup an IAM API Key [here](https://cloud.ibm.com/iam/apikeys).

Once you have the credentials, there are two options to configure PyWren: Using a configuration file or using a Python dictionary in the runtime:


### Using configuration file
Copy the `config_template.yaml.` into `~/.pywren_config`

Edit `~/.pywren_config` and configure the following entries:

```yaml
pywren: 
    storage_bucket: <BUCKET_NAME>

#ibm:
    #iam_api_key: <IAM_API_KEY>

ibm_cf:
    # Region endpoint example: https://us-east.functions.cloud.ibm.com
    endpoint    : <REGION_ENDPOINT>  # make sure to use https:// as prefix
    namespace   : <NAMESPACE>
    api_key     : <API_KEY>  # Not needed if using IAM API Key
    # namespace_id : <NAMESPACE_ID>  # Mandatory if using IAM API Key
   
ibm_cos:
    # Region endpoint example: https://s3.us-east.cloud-object-storage.appdomain.cloud
    endpoint   : <REGION_ENDPOINT>  # make sure to use https:// as prefix
    api_key    : <API_KEY>  # Not needed if using IAM API Key
    # alternatively you can use HMAC authentication method
    # access_key : <ACCESS_KEY>
    # secret_key : <SECRET_KEY>
```

You can choose different name for the config file or keep it into different folder. If this is the case make sure you configure system variable 
	
	PYWREN_CONFIG_FILE=<LOCATION OF THE CONFIG FILE>

Once the configuration file is created, you can obtain an IBM-PyWren executor by:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor()
```

### Configuration in the runtime
This option allows you pass all the configuration details as part of the PyWren invocation in runtime. All you need is to configure a Python dictionary with keys and values, for example:

```python
config = {'pywren' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'HOST', 
                      'namespace': 'NAMESPACE', 
                      'api_key': 'API_KEY'}, 

          'ibm_cos': {'endpoint': 'REGION_ENDPOINT', 
                      'api_key': 'API_KEY'}}
```

Once created, you can obtain an IBM-PyWren executor by:

```python
import pywren_ibm_cloud as pywren
pw = pywren.ibm_cf_executor(config=config)
```

## Using RabbitMQ to monitor function activations
By default, IBM-PyWren uses the IBM Cloud Object Storage service to monitor function activations: Each function activation stores a file named *{id}/status.json* to the Object Storage when it finishes its execution. This file contains some statistics about the execution, including if the function activation ran successfully or not. Having these files, the default monitoring approach is based on polling the Object Store each X seconds to know which function activations have finished and which not.

As this default approach can slow-down the total application execution time, due to the number of requests it has to make against the object store, in IBM-PyWren we integrated a RabitMQ service to monitor function activations in real-time. With RabitMQ, the content of the *{id}/status.json* file is sent trough a queue. This speeds-up total application execution time, since PyWren only needs one connection to the messaging service to monitor all function activations. We currently support the AMQP protocol. To enable PyWren to use this service, add the *AMQP_URL* key into the *rabbitmq* section in the configuration, for example:

```yaml
rabbitmq: 
    amqp_url: <AMQP_URL>  # amqp://
```

In addition, activate the monitoring service by writing *rabbitmq_monitor : True* in the configuration (pywren section), or in the executor by:

```python
pw = pywren.ibm_cf_executor(rabbitmq_monitor=True)
```

## Configuration keys

### Summary of configuration keys for PyWren:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|pywren|storage_bucket | |yes | Any bucket that exists in your COS account. This will be used by PyWren for intermediate data |
|pywren|data_cleaner |True|no|If set to True, then cleaner will automatically delete temporary data that was written into `storage_bucket/pywren.jobs`|
|pywren | storage_backend | ibm_cos | no | Storage backend implementation. IBM Cloud Object Storage is the default |
|pywren | compute_backend | ibm_cf | no | Compute backend implementation. IBM Cloud Functions is the default |
|pywren | rabbitmq_monitor | False | no | Activate the rabbitmq monitoring feature |
|pywren | workers | Depends of the ComputeBackend | no | Max number of concurrent workers |
|pywren| runtime_timeout | 600 |no |  Default runtime timeout (in seconds) |
|pywren| runtime_memory | 256 | no | Default runtime memory (in MB) |


### Summary of configuration keys for IBM Cloud:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |


### Summary of configuration keys for IBM Cloud Functions:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cf| endpoint | |yes | IBM Cloud Functions endpoint from [here](https://cloud.ibm.com/docs/openwhisk?topic=cloud-functions-cloudfunctions_regions#cloud-functions-endpoints). Make sure to use https:// prefix, for example: https://us-east.functions.cloud.ibm.com |
|ibm_cf| namespace | |yes | Value of CURRENT NAMESPACE from [here](https://cloud.ibm.com/functions/namespace-settings) |
|ibm_cf| api_key |  | no | **Mandatory** if using Cloud Foundry-based namespace. Value of 'KEY' from [here](https://cloud.ibm.com/functions/namespace-settings)|
|ibm_cf| namespace_id |  |no | **Mandatory** if using IAM-based namespace with IAM API Key. Value of 'GUID' from [here](https://cloud.ibm.com/functions/namespace-settings)|


### Summary of configuration keys for IBM Cloud Object Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cos | endpoint | |yes | Regional endpoint to your COS account. Make sure to use full path with 'https://' as prefix. For example https://s3.us-east.cloud-object-storage.appdomain.cloud |
|ibm_cos | private_endpoint | |no | Private regional endpoint to your COS account. Make sure to use full path. For example: https://s3.private.us-east.cloud-object-storage.appdomain.cloud |
|ibm_cos | api_key | |no | API Key to your COS account. **Mandatory** if no access_key and secret_key. Not needed if using IAM API Key|
|ibm_cos | access_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
|ibm_cos | secret_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|


### Summary of configuration keys for RabbitMQ

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| rabbitmq |amqp_url | |no | AMQP URL from RabbitMQ service. Make sure to use amqp:// prefix |


### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | docker_user | |yes | Docker hub username |
|knative | docker_token | |yes | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
