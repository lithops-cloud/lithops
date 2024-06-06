# IBM Cloud Object Storage

Lithops with IBM COS as storage backend.

## Installation

1. Install IBM Cloud backend dependencies:

```bash
python3 -m pip install lithops[ibm]
```

2. Create an [IBM Cloud Object Storage account](https://www.ibm.com/cloud/object-storage).

3. Crate a bucket in your desired region. Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

1. Create the credentials to access to your COS account (Choose one option):
 
### Option 1 (COS API Key):

2. In the side navigation, click `Service Credentials`.

3. Click `New credential +` and provide the necessary information.

4. Click `Add` to generate service credential.

5. Click `View credentials` and copy the *apikey* value.

6. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        region   : <REGION>
        api_key  : <API_KEY>
        storage_bucket: <BUCKET_NAME>
    ```

### Option 2 (COS HMAC credentials):

2. In the side navigation, click `Service Credentials`.

3. Click `New credential +`.

4. Click on advanced options and enable `Include HMAC Credential` button. 

5. Click `Add` to generate service credential.

6. Click `View credentials` and copy the *access_key_id* and *secret_access_key* values.

7. When using HMAC credentials, you can omit providing an storage bucket, since Lithops will be able to create it automatically.

8. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        region: <REGION>  
        access_key_id: <ACCESS_KEY_ID>
        secret_access_key: <SECRET_ACCESS_KEY_ID>
    ```


### Option 3 (IBM IAM API Key):

2. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys)

3. Click `Create an IBM Cloud API Key` and provide the necessary information.

4. Copy the generated IAM API key (You can only see the key the first time you create it, so make sure to copy it).

5. Edit your lithops config file and add the following keys:

    ```yaml
    lithops:
        storage_backend: ibm_cos
    ibm:
        iam_api_key: <IAM_API_KEY>

    ibm_cos:
        region: <REGION>
        storage_bucket: <BUCKET_NAME>
    ```

## Lithops COS Endpoint configuration

### Using region
The easiest approach is to let Lithops to choose the right endpoint by itself. To enable this, just configure Lithops with the region name of your `storage_bucket`, as follows:

```yaml
    ibm_cos:
        region   : <REGION>
```

Valid region names are: `us-east`, `us-south`, `eu-gb`, `eu-de`, etc..

### Using endpoints path

Alternative to using region, you can configure the public and private endpoints as follows:

1. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

2. In the side navigation, click `Endpoints` to find your COS endpoints. You must copy both `public` and `private` endpoints of the region where you created your bucket.

```yaml
    ibm_cos:
        endpoint: https://s3.<region>.cloud-object-storage_config.appdomain.cloud
        private_endpoint: https://s3.private.<region>.cloud-object-storage_config.appdomain.cloud 
```


## Summary of configuration keys for IBM Cloud:

### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM services. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |
|ibm | region | |no | IBM Region.  One of: `eu-gb`, `eu-de`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd` |
|ibm | resource_group_id | | no | Resource group id from your IBM Cloud account. Get it from [here](https://cloud.ibm.com/account/resource-groups) |

### IBM Cloud Object Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_cos | region | |yes | Region of your bucket. One of: `eu-gb`, `eu-de`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd`. Lithops will use the region set under the `ibm` section if it is not set here|
|ibm_cos | api_key | |yes | API Key to your COS account. Not needed if using IAM API Key|
|ibm_cos | storage_bucket | | yes | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. You must provide HMAC Credentials if you want the bucket to be automatically created |
|ibm_cos | access_key_id | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
|ibm_cos | secret_access_key | |no | HMAC Credentials. **Mandatory** if no api_key. Not needed if using IAM API Key|
|ibm_cos | endpoint | |no | Endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' as prefix |
|ibm_cos | private_endpoint | |no | Private endpoint to your COS account. **Mandatory** if no region. Make sure to use the full path with 'https://' or http:// as prefix |
