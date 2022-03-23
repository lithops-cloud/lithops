# Google Cloud Functions

Lithops with *GCP Functions* as serverless compute backend.

## Installation

1. Install Google Cloud Platform backend dependencies:

```
$ python3 -m install lithops[gcp]
```

2. [Login](https://console.cloud.google.com) to Google Cloud Console (or sign up if you don't have an account).

3. Create a new project. Name it `lithops` or similar.

4. Navigate to *IAM & Admin* > *Service Accounts*.

5. Click on *Create Service Account*. Name the service account `lithops-executor` or similar. Then click on *Create*.

6. Add the following roles to the service account:
 - Service Account User
 - Cloud Functions Admin
 - Pub/Sub Admin
 - Storage Admin

7. Click on *Continue*. Then, click on *Create key*. Select *JSON* and then *Create*. Download the JSON file to a secure location in you computer. Click *Done*.

8. Enable **Google Cloud Build** API: Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Cloud Build API" at the search bar. Click *Enable*.

## Configuration

1. Edit your lithops config and add the following keys:

```yaml
    lithops:
        backend: gcp_functions

    gcp:
        project_name : <PROJECT_ID>
        service_account : <SERVICE_ACCOUNT_EMAIL>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
        region : <REGION_NAME>
```
 
## Summary of configuration keys for Google:

### Google Cloud Platform:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp | project_name | |yes | Project id given by Google Cloud Platform in step 3 (e.g. `lithops-876385`) |
|gcp | service_account | |yes | Service account email of the service account created on step 5 (e.g. `lithops-executor@lithops.iam.gserviceaccount.com`) |
|gcp | credentials_path | |yes | **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`) |
|gcp | region | |yes | Region of the bucket created at step 8. Functions and pub/sub queue will be created in the same region (e.g. `us-east1`) |

### Google Cloud Functions
|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_functions | max_workers | 1000 | no | Max number of workers per `FunctionExecutor()`|
|gcp_functions | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|gcp_functions | runtime |  |no | Runtime name already deployed in the service |
|gcp_functions | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|gcp_functions | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|gcp_functions | invoke_pool_threads | 1000 |no | Number of concurrent threads used for invocation |
