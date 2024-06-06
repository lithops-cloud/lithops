# Google Cloud Functions

Lithops with *GCP Functions* as serverless compute backend.

## Installation

1. Install Google Cloud Platform backend dependencies:

```bash
python3 -m pip install lithops[gcp]
```

2. [Login](https://console.cloud.google.com) to Google Cloud Console (or sign up if you don't have an account).

3. Create a new project. Name it `lithops` or similar.

4. Navigate to *IAM & Admin* > *Service Accounts*.

5. Click on *Create Service Account*. Name the service account `lithops-executor` or similar. Then click on *Create*.

6. Add the following roles to the service account:
 - Service Accounts --> Service Account User
 - Cloud Functions --> Cloud Functions Admin
 - Pub/Sub --> Pub/Sub Admin
 - Cloud Storage --> Storage Admin

7. Click on *Continue* and *Done*. Next, access the newly created service account, and click on the *keys* tab. Click on *Add key*. Select *JSON* and then *Create*. Download the JSON file to a secure location in you computer.

8. Enable the **Cloud Build API** : Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Cloud Build API" at the search bar. Click *Enable*.

9. Enable the **Cloud Functions API** : Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Cloud Functions API" at the search bar. Click *Enable*.

10. Enable the **Artifact Registry API**: Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Artifact Registry API" at the search bar. Click *Enable*.

## Configuration

1. Edit your lithops config and add the following keys:

```yaml
    lithops:
        backend: gcp_functions

    gcp:
        region : <REGION_NAME>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
```
 
## Summary of configuration keys for Google:

### Google Cloud Platform:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp | region | |yes | Region name of the GCP services (e.g. `us-east1`) |
|gcp | credentials_path | |yes | **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`). Alternatively you can set `GOOGLE_APPLICATION_CREDENTIALS` environment variable. If not provided it will try to load the default credentials from the environment|

### Google Cloud Functions
|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_functions | region | |no | Region name (e.g. `us-east1`). Functions and pub/sub queues will be created in the same region. Lithops will use the region set under the `gcp` section if it is not set here  |
|gcp_functions | max_workers | 1000 | no | Max number of workers per `FunctionExecutor()`|
|gcp_functions | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|gcp_functions | runtime |  |no | Runtime name already deployed in the service |
|gcp_functions | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|gcp_functions | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|gcp_functions | trigger | pub/sub  | no | One of 'https' or 'pub/sub'|
|gcp_functions | invoke_pool_threads | 1000 |no | Number of concurrent threads used for invocation |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b gcp_functions -s gcp_storage
```


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```