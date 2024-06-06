# GCP Storage

Lithops with GCP Storage as storage backend.

## Installation

1. Install Google Cloud Platform backend dependencies:

```bash
python3 -m pip install lithops[gcp]
```

## Configuration

1. [Login](https://console.cloud.google.com) to Google Cloud Console (or signup if you don't have an account).
 
2. Create a new project. Name it `lithops` or similar.
 
3. Navigate to *IAM & Admin* > *Service Accounts*.
 
4. Click on *Create Service Account*. Name the service account `lithops-executor` or similar. Then click on *Create*.
 
5. Add the following roles to the service account:
	- Service Account User
	- Cloud Functions Admin
	- Pub/Sub Admin
	- Storage Admin

6. Click on *Continue*. Then, click on *Create key*. Select *JSON* and then *Create*. Download the JSON file to a secure location in you computer. Click *Done*.

7. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: gcp_storage

    gcp:
        region : <REGION_NAME>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
```
 
## Summary of configuration keys for Google:

### Google Cloud Platform:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp | region | |yes | Region of the bucket created at step 8. Functions and pub/sub queue will be created in the same region (e.g. `us-east1`) |
|gcp | credentials_path | |yes | **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`). Alternatively you can set `GOOGLE_APPLICATION_CREDENTIALS` environment variable. If not provided it will try to load the default credentials from the environment |

### Google Cloud Storage
|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_storage | region | |no | Region Name (e.g. `us-east1`). Lithops will use the region set under the `gcp` section if it is not set here |
|gcp_storage | storage_bucket | | no | The name of a bucket that exists in your account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided|
 
