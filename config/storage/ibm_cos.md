# Lithops on IBM Cloud Object Storage


Lithops with IBM COS as storage backend.


### Installation

1. Create an [IBM Cloud Object Storage account](https://www.ibm.com/cloud/object-storage).

2. Crate a bucket in your desired region. Remember to update the corresponding Lithops config field with this bucket name.

3. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

4. In the side navigation, click `Endpoints` to find your `region`, `API public` and `private endpoints`.

### Lithops COS Endpoint configuration

#### Using region
The easiest apporach is to let Lithops to choose the right endpoint by itself. To enable this, just configure Lithops with the region name of your `storage_bucket`, as follows:

```yaml
    ibm_cos:
        region   : <REGION>
```

Valid region names are: us-east, us-south, eu-gb, eu-de, etc..

### Using endpoints path
Alternative to using region, you can configure the public and private endpoints as follows:

```yaml
    ibm_cos:
        endpoint: https://s3.<region>.cloud-object-storage.appdomain.cloud
        private_endpoint: https://s3.private.<region>.cloud-object-storage.appdomain.cloud 
```

### Configuration

1. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

2. In the side navigation, click `Endpoints` to find your API endpoint. You must copy both public and private endpoints of the region where you created your bucket.

3. Create the credentials to access to your COS account (Choose one option):
 
#### Option 1 (COS API Key):

4. In the side navigation, click `Service Credentials`.

5. Click `New credential +` and provide the necessary information.

6. Click `Add` to generate service credential.

7. Click `View credentials` and copy the *apikey* value.

8. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        storage_bucket: <BUCKET_NAME>
        region   : <REGION>
        api_key  : <API_KEY>
    ```

#### Option 2 (COS HMAC credentials):

4. In the side navigation, click `Service Credentials`.

5. Click `New credential +`.

6. Click on advanced options and enable `Include HMAC Credential` button. 

7. Click `Add` to generate service credential.

8. Click `View credentials` and copy the *access_key_id* and *secret_access_key* values.

9. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        storage_bucket: <BUCKET_NAME>
        region : <REGION>  
        access_key  : <ACCESS_KEY_ID>
        secret_key  : <SECRET_KEY_ID>
    ```

#### Option 3 (IBM IAM API Key):

4. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys)

5. Click `Create an IBM Cloud API Key` and provide the necessary information.

6. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

7. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage_backend: ibm_cos

    ibm:
        iam_api_key: <IAM_API_KEY>
       
    ibm_cos:
        storage_bucket: <BUCKET_NAME>
        region : <REGION>
    ```

### Summary of configuration keys for IBM Cloud:

#### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM COS and IBM Cloud Functions. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |


#### IBM Cloud Object Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cos | storage_bucket | | yes | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in `lithops` section |
|ibm_cos | region | |no | Region of your bucket. **Mandatory** if no endpoint. For example: us-east, us-south, eu-gb, eu-de, etc..|
|ibm_cos | endpoint | |no | Endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' as prefix. |
|ibm_cos | private_endpoint | |no | Private endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' or http:// as prefix. |
|ibm_cos | api_key | |no | API Key to your COS account. **Mandatory** if no access_key and secret_key. Not needed if using IAM API Key|
|ibm_cos | access_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
|ibm_cos | secret_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
