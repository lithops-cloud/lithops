# Lithops on IBM Cloud Functions

Lithops with *IBM Cloud Functions* as compute backend.

### Configuration

1. Login to IBM Cloud and open up your [dashboard](https://cloud.ibm.com/).

 
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

10. Copy the "current namespace" name and the API key.

11. Navigate [here](https://cloud.ibm.com/docs/openwhisk?topic=openwhisk-cloudfunctions_regions#cloudfunctions_endpoints) and copy your functions endpoint. It must be in the same region where you created the namespace.

12. Edit your lithops config and add the following keys:
    ```yaml
    serverless:
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

7. From this page copy the namespace name and the namespace GUID.

8. Navigate [here](https://cloud.ibm.com/docs/openwhisk?topic=openwhisk-cloudfunctions_regions#cloud-functions-endpoints) and choose your functions endpoint. It must be in the same region where you created the namespace.

9. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys).

10. Click `Create an IBM Cloud API Key` and provide the necessary information.

11. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

12. Edit your lithops config and add the following keys:
    ```yaml
    serverless:
        backend: ibm_cf
        
    ibm:
        iam_api_key: <IAM_API_KEY>
       
    ibm_cf:
        endpoint     : <REGION_ENDPOINT>
        namespace    : <NAMESPACE>
        namespace_id : <GUID>
    ```
    
### Summary of configuration keys for IBM Cloud:

#### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |

#### IBM Cloud Functions:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cf| endpoint | |yes | IBM Cloud Functions endpoint from [here](https://cloud.ibm.com/docs/openwhisk?topic=cloud-functions-cloudfunctions_regions#cloud-functions-endpoints). Make sure to use https:// prefix, for example: https://us-east.functions.cloud.ibm.com |
|ibm_cf| namespace | |yes | Value of CURRENT NAMESPACE from [here](https://cloud.ibm.com/functions/namespace-settings) |
|ibm_cf| api_key |  | no | **Mandatory** if using Cloud Foundry-based namespace. Value of 'KEY' from [here](https://cloud.ibm.com/functions/namespace-settings)|
|ibm_cf| namespace_id |  |no | **Mandatory** if using IAM-based namespace with IAM API Key. Value of 'GUID' from [here](https://cloud.ibm.com/functions/namespace-settings)|
|ibm_cf| runtime |  |no | Docker image name.|
