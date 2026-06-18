# IBM Cloud Object Storage

Lithops with IBM COS as storage backend.

## Installation

1. Install IBM Cloud backend dependencies:

```bash
python3 -m pip install lithops[ibm]
```

2. Create an [IBM Cloud Object Storage account](https://www.ibm.com/cloud/object-storage).

3. Create a bucket in your desired region. Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

Choose one authentication option below.

### Option 1 (COS API Key):

1. In the side navigation, click `Service Credentials`.

2. Click `New credential +` and provide the necessary information.

3. Click `Add` to generate service credential.

4. Click `View credentials` and copy the *apikey* value.

5. Edit your Lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        region   : <REGION>
        api_key  : <API_KEY>
        storage_bucket: <BUCKET_NAME>
    ```

### Option 2 (COS HMAC credentials):

1. In the side navigation, click `Service Credentials`.

2. Click `New credential +`.

3. Click on advanced options and enable `Include HMAC Credential` button. 

4. Click `Add` to generate service credential.

5. Click `View credentials` and copy the *access_key_id* and *secret_access_key* values.

6. When using HMAC credentials, you can omit providing a storage bucket, since Lithops will be able to create it automatically.

7. Edit your Lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos
       
    ibm_cos:
        region: <REGION>  
        access_key_id: <ACCESS_KEY_ID>
        secret_access_key: <SECRET_ACCESS_KEY>
    ```


### Option 3 (IBM IAM API Key):

1. If you don't have an IAM API key created, navigate to the [IBM IAM dashboard](https://cloud.ibm.com/iam/apikeys)

2. Click `Create an IBM Cloud API Key` and provide the necessary information.

3. Copy the generated IAM API key (you can only see the key the first time you create it, so make sure to copy it).

4. Edit your Lithops config file and add the following keys:

    ```yaml
    lithops:
        storage: ibm_cos

    ibm:
        iam_api_key: <IAM_API_KEY>

    ibm_cos:
        region: <REGION>
        storage_bucket: <BUCKET_NAME>
    ```

## Lithops COS Endpoint configuration

### Using region (recommended)

The easiest approach is to let Lithops choose the right endpoint by itself. Configure Lithops with the region name of your `storage_bucket`:

```yaml
    ibm_cos:
        region   : <REGION>
```

Valid region names include: `us-east`, `us-south`, `eu-gb`, `eu-de`, `eu-es`, `ca-tor`, `br-sao`, `jp-tok`, `jp-osa`, `au-syd`.

When `region` is set, Lithops automatically configures:

- **Public endpoint** (client): `https://s3.<region>.cloud-object-storage.appdomain.cloud`
- **Worker endpoint** (`code_engine` and `ibm_vpc`): `https://s3.direct.<region>.cloud-object-storage.appdomain.cloud`

You do not need to set `endpoint` or `private_endpoint` manually when using `region` with these backends.

### Using endpoint paths

As an alternative to using `region`, you can configure the public and worker endpoints explicitly:

1. Login to IBM Cloud and open up your dashboard. Then navigate to your instance of Object Storage.

2. In the side navigation, click `Endpoints` to find your COS endpoints. Copy the endpoint for the region where you created your bucket.

```yaml
    ibm_cos:
        endpoint: https://s3.<region>.cloud-object-storage.appdomain.cloud
        private_endpoint: https://s3.direct.<region>.cloud-object-storage.appdomain.cloud
```

Use the **direct** endpoint (`s3.direct`) as `private_endpoint` when running Lithops with `code_engine` or `ibm_vpc`.


## Summary of configuration keys for IBM Cloud:

### IBM IAM:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm | iam_api_key | |no | IBM Cloud IAM API key to authenticate against IBM services. Obtain the key [here](https://cloud.ibm.com/iam/apikeys) |
|ibm | region | |no | IBM Region. One of: `eu-gb`, `eu-de`, `eu-es`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd` |
|ibm | resource_group_id | | no | Resource group id from your IBM Cloud account. Get it from [here](https://cloud.ibm.com/account/resource-groups) |

### IBM Cloud Object Storage:

| Group   | Key                 |Default|Mandatory| Additional info                                                                                                                                                                                         |
|---------|---------------------|---|---|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| ibm_cos | region              | |yes* | Region of your bucket. One of: `eu-gb`, `eu-de`, `eu-es`, `us-south`, `us-east`, `br-sao`, `ca-tor`, `jp-tok`, `jp-osa`, `au-syd`. Lithops uses the region set under the `ibm` section if it is not set here. *Not required if `endpoint` is set |
| ibm_cos | api_key             | |no | API Key to your COS account. Required for Option 1 |
| ibm_cos | storage_bucket      | |yes* | Bucket used by Lithops for intermediate data. *Can be auto-created when using HMAC credentials |
| ibm_cos | service_instance_id | |no | The service instance (CRN format) of your COS instance. Required if neither HMAC credentials nor `api_key` are provided |
| ibm_cos | access_key_id       | |no | HMAC credentials. Required for Option 2 |
| ibm_cos | secret_access_key   | |no | HMAC credentials. Required for Option 2 |
| ibm_cos | endpoint            | |no | Public endpoint to your COS account. Auto-set from `region` if not provided. Must start with `https://` |
| ibm_cos | private_endpoint    | |no | Worker endpoint for compute backends. Auto-set from `region` for `code_engine` and `ibm_vpc`. Must start with `https://` or `http://` |
