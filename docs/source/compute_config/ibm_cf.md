# IBM Cloud Functions

Lithops with *IBM Cloud Functions* as compute backend.

**Note**: This backend is deprecated. See the [deprecation overview](https://cloud.ibm.com/docs/openwhisk?topic=openwhisk-dep-overview)

## Installation

1. Install IBM Cloud backend dependencies:

```bash
python3 -m pip install lithops[ibm]
```

## Configuration

1. Login to IBM Cloud and open up your [dashboard](https://cloud.ibm.com/).

2. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys).

3. Click `Create an IBM Cloud API Key` and provide the necessary information.

4. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

5. Navigate to the [resource groups dashboard](https://cloud.ibm.com/account/resource-groups), and copy the desired resource group ID.

5. Edit your lithops config and add the following keys:

    ```yaml
    lithops:
        backend: ibm_cf
        
    ibm:
        iam_api_key: <IAM_API_KEY>
        region: <REGION>
        resource_group_id: <RESOURCE_GROUP_ID>
    ```

## Summary of configuration keys for IBM Cloud:

### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |yes | IBM Cloud IAM API key to authenticate against IBM services. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |
|ibm | region | |yes | IBM Region.  One of: `eu-gb`, `eu-de`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd` |
|ibm | resource_group_id | | yes | Resource group id from your IBM Cloud account. Get it from [here](https://cloud.ibm.com/account/resource-groups) |

### IBM Cloud Functions:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cf| namespace | |no | Value of CURRENT NAMESPACE from [here](https://cloud.ibm.com/functions/namespace-settings). Provide it if you want to use an existing `namespace`. Lithops will automatically create a new namespace if not provided.|
|ibm_cf| namespace_id |  |no |  Value of 'GUID' from [here](https://cloud.ibm.com/functions/namespace-settings). Provide it if you want to use an existing `namespace`. Provide it along with `namespace`.|
|ibm_cf | region | |no | Service region. One of: `jp-tok`, `au-syd`, `eu-gb`, `eu-de`, `us-south`, `us-east`. Lithops will use the `region` set under the `ibm` section if it is not set here |
|ibm_cf| endpoint | |no | IBM Cloud Functions endpoint (if region not provided). Make sure to use https:// prefix, for example: https://us-east.functions.cloud.ibm.com |
|ibm_cf | max_workers | 1200 | no | Max number of workers per `FunctionExecutor()`|
|ibm_cf | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|ibm_cf| runtime |  |no | Docker image name.|
|ibm_cf | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|ibm_cf | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |
|ibm_cf | invoke_pool_threads | 500 |no | Number of concurrent threads used for invocation |
|ibm_cf | remote_invoker | False | no |  Activate the remote invoker feature that uses one cloud function to spawn all the actual `map()` activations |
|ibm_cf | runtime_include_function | False | no | If set to true, Lithops will automatically build a new runtime, including the function's code, instead of transferring it through the storage backend at invocation time. This is useful when the function's code size is large (in the order of 10s of MB) and the code does not change frequently |


## Test Lithops

Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b ibm_cf -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```