# Google Cloud Run

Lithops with *GCP Cloud Run* as serverless compute backend.

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
 - Cloud Run --> Cloud Run Admin
 - Cloud Storage -->Storage Admin

7. Click on *Continue*. Then, click on *Create key*. Select *JSON* and then *Create*. Download the JSON file to a secure location in you computer. Click *Done*.

8. Enable the **Cloud Build API** : Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Cloud Build API" at the search bar. Click *Enable*.

9. Enable the **Cloud Run API** : Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Cloud Run API" at the search bar. Click *Enable*.

10. Enable the **Artifact Registry API**: Navigate to *APIs & services* tab on the menu. Click *ENABLE APIS AND SERVICES*. Look for "Artifact Registry API" at the search bar. Click *Enable*.

## Configuration

1. Edit your lithops config and add the following keys:

```yaml
    lithops:
        backend: gcp_cloudrun

    gcp:
        region : <REGION_NAME>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
```

## Summary of configuration keys for Google Cloud

### Google Cloud Platform:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp | region | |yes | Region name of the GCP services (e.g. `us-east1`) |
|gcp | credentials_path | | yes | **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`). Alternatively you can set `GOOGLE_APPLICATION_CREDENTIALS` environment variable. If not provided it will try to load the default credentials from the environment|

### Google Cloud Run
|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_cloudrun | region | |no | Region name (e.g. `us-east1`). Lithops will use the region set under the `gcp` section if it is not set here |
|gcp_cloudrun | min_workers | 0 | no | Minimum number of workers of a given runtime to keep in warm status|
|gcp_cloudrun | max_workers | 1000 | no | Maximum number of workers to scale a given runtime|
|gcp_cloudrun | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker. It is recommendable to set this value to the same number of CPUs of the container. |
|gcp_cloudrun | runtime |  |no | Container image name|
|gcp_cloudrun | runtime_cpu | 0.25 |no | CPU limit. Default 0.25vCPU |
|gcp_cloudrun | runtime_memory | 256 |no | Memory limit in MB. Default 256Mi |
|gcp_cloudrun | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|gcp_cloudrun | trigger | https  | no | Currently it supports 'https' trigger|
|gcp_cloudrun | invoke_pool_threads | 100 |no | Number of concurrent threads used for invocation |
|gcp_cloudrun | runtime_include_function | False | no | If set to true, Lithops will automatically build a new runtime, including the function's code, instead of transferring it through the storage backend at invocation time. This is useful when the function's code size is large (in the order of 10s of MB) and the code does not change frequently |

## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b gcp_cloudrun -s gcp_storage
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```