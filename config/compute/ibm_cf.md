# Lithops on IBM Cloud Functions

Lithops with *IBM Cloud Functions* as compute backend.

### Configuration

1. Login to IBM Cloud and open up your [dashboard](https://cloud.ibm.com/).

- **Important Note: If you have a free/student account, please choose Option 1 one and start from step 8**
 
#### Option 1 (CloudFoundy-based namespace):

By default, the IBM Cloud account provides an automatically created CloudFoundry namespace for your functions. Namespaces are only valid for the regions where they were created. If you don't plan to create a new namespace to execute functions in another region, you can skip to step 8.

2. Navigate to your [CloudFoundry account settings](https://cloud.ibm.com/account/cloud-foundry).

3. Click `Create +` and provide the necessary information.

4. Click `Save` to create the new CloudFoundry organization.

5. Click on your recently created organization.

6. Click `Add a space +` and provide the necessary information.

7. Click `Save` to create the space in the region you choose.

8. Navigate to the [namespace settings](https://cloud.ibm.com/functions/namespace-settings) of your Cloud Functions dashboard.

9. Choose your namespace from the "current namespace" dropdown menu. 

10. Copy the full **current namespace** name and the **API key**. Usually, namepsace names in free accounts looks like *your.name@myemail.com_dev*, e.g, *james.braun@gmail.com_dev*

11. From the same page, check the **Location** of your namespace and select the appropriate endpoint [from the table below](#ibm-cloud-functions-namespace-endpoints).

12. Edit your lithops config and add the following keys:

    ```yaml
    lithops:
        backend: ibm_cf
       
    ibm_cf:
        endpoint    : <REGION_ENDPOINT>
        namespace   : <NAMESPACE>
        api_key     : <API_KEY>
    ```


#### Option 2 (IBM IAM-based namespace):

2. Navigate to the [namespace settings](https://cloud.ibm.com/functions/namespace-settings) of your Cloud Functions dashboard.

3. Click on the "current namespace" dropdown menu.

4. Click `Create Namespace +` and provide the necessary information.

5. Click `Create` to create the IAM-based namespace in the region you choose.

6. Choose your new namespace from the "current namespace" dropdown menu.

7. From the same page, copy the **namespace name** and the **namespace GUID**.

8. From the same page, check the **Location** of your namespace and select the appropriate endpoint [from the table below](#ibm-cloud-functions-namespace-endpoints).

9. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys).

10. Click `Create an IBM Cloud API Key` and provide the necessary information.

11. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

12. Edit your lithops config and add the following keys:

    ```yaml
    lithops:
        backend: ibm_cf
        
    ibm:
        iam_api_key: <IAM_API_KEY>
       
    ibm_cf:
        endpoint     : <REGION_ENDPOINT>
        namespace    : <NAMESPACE>
        namespace_id : <GUID>
    ```
    
### IBM Cloud Functions Namespace Endpoints

|Location| Endpoint|
|---|---|
|Washington DC | https://us-east.functions.cloud.ibm.com |
|Dallas | https://us-south.functions.cloud.ibm.com |
|London | https://eu-gb.functions.cloud.ibm.com |
|Frankfur | https://eu-de.functions.cloud.ibm.com |
|Tokyo | https://jp-tok.functions.cloud.ibm.com |
|Sydney | https://au-syd.functions.cloud.ibm.com |

    
### Summary of configuration keys for IBM Cloud:

#### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |

#### IBM Cloud Functions:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cf| endpoint | |yes | IBM Cloud Functions endpoint. Make sure to use https:// prefix, for example: https://us-east.functions.cloud.ibm.com |
|ibm_cf| namespace | |yes | Value of CURRENT NAMESPACE from [here](https://cloud.ibm.com/functions/namespace-settings) |
|ibm_cf| api_key |  | no | **Mandatory** if using Cloud Foundry-based namespace. Value of 'KEY' from [here](https://cloud.ibm.com/functions/namespace-settings)|
|ibm_cf| namespace_id |  |no | **Mandatory** if using IAM-based namespace with IAM API Key. Value of 'GUID' from [here](https://cloud.ibm.com/functions/namespace-settings)|
|ibm_cf | max_workers | 1200 | no | Max number of workers per `FunctionExecutor()`|
|ibm_cf | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|ibm_cf| runtime |  |no | Docker image name.|
|ibm_cf | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|ibm_cf | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 600 seconds |
|ibm_cf | invoke_pool_threads | 500 |no | Number of concurrent threads used for invocation |
|ibm_cf | remote_invoker | False | no |  Activate the remote invoker feature that uses one cloud function to spawn all the actual `map()` activations |
