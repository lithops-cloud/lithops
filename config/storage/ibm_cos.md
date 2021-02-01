# Lithops on IBM Cloud Object Storage


Lithops with IBM COS as storage backend.


### Installation

1. Create an [IBM Cloud Object Storage account](https://www.ibm.com/cloud/object-storage).

2. Crate a bucket in your desired region.
3. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

4. In the side navigation, click `Endpoints` to find your `region`, `API public` and `private endpoints`.

### Lithops COS Endpoint configuration
#### Using region
The easiest apporach is to let Lithops to choose the right endpoint by itself. To enable this, just configure Lithops with region name only, as follows

    ```yaml
    ibm_cos:
        region   : <REGION>
    ```
### Using endpoints path
Alternative to using region, you can configre public and private endpoints as follows

    ```yaml
	 ibm_cos:
        private_endpoint: https://s3.private.<region>cloud-object-storage.appdomain.cloud
        endpoint: https://s3.<region>.cloud-object-storage.appdomain.cloud
    ```

### Configuration

5. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

6. In the side navigation, click `Endpoints` to find your API endpoint. You must copy both public and private endpoints of the region where you created your bucket.

7. Create the credentials to access to your COS account (Choose one option):
 
#### Option 1 (COS API Key):

8. In the side navigation, click `Service Credentials`.

9. Click `New credential +` and provide the necessary information.

10. Click `Add` to generate service credential.

11. Click `View credentials` and copy the *apikey* value.

12. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
        storage_bucket: <BUCKET_NAME>
       
    ibm_cos:
       region   : <REGION>
       api_key    : <API_KEY>
    ```

#### Option 2 (COS HMAC credentials):

13. In the side navigation, click `Service Credentials`.

14. Click `New credential +`.

15. Click on advanced options and enable `Include HMAC Credential` button. 

16. Click `Add` to generate service credential.

17. Click `View credentials` and copy the *access_key_id* and *secret_access_key* values.

18. Edit your lithops config file and add the following keys:
    ```yaml
    lithops:
        storage: ibm_cos
        storage_bucket: <BUCKET_NAME>
       
    ibm_cos:
       region   : <REGION>  
       access_key    : <ACCESS_KEY_ID>
       secret_key    : <SECRET_KEY_ID>
    ```

#### Option 3 (IBM IAM API Key):

19. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys)

20. Click `Create an IBM Cloud API Key` and provide the necessary information.

21. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

22. Edit your lithops config file and add the following keys:
    ```yaml
    lithops:
        storage_backend: ibm_cos
        storage_bucket: <BUCKET_NAME>
        
    ibm:
        iam_api_key: <IAM_API_KEY>
       
    ibm_cos:
        region   : <REGION>
    ```

### Summary of configuration keys for IBM Cloud:

#### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |


#### IBM Cloud Object Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cos | storage_bucket | |yes | Storage bucket in your COS |
|ibm_cos | region | |no | Region of your bucket. **Mandatory** if no endpoint. For example: us-east, us-south, eu-gb, eu-de, etc..|
|ibm_cos | endpoint | |no | Endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' as prefix. |
|ibm_cos | private_endpoint | |no | Private endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' or http:// as prefix. |
|ibm_cos | api_key | |no | API Key to your COS account. **Mandatory** if no access_key and secret_key. Not needed if using IAM API Key|
|ibm_cos | access_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
|ibm_cos | secret_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|

