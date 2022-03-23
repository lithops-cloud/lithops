# GCP Storage

Lithops with GCP Storage as storage backend.

## Installation

1. Install Google Cloud Platform backend dependencies:

```
$ python3 -m pip install lithops[gcp]
```

 2. [Login](https://console.cloud.google.com) to Google Cloud Console (or signup if you don't have an account).
 
 3. Create a new project. Name it `lithops` or similar.
 
 4. Navigate to *IAM & Admin* > *Service Accounts*.
 
 5. Click on *Create Service Account*. Name the service account `lithops-executor` or similar. Then click on *Create*.
 
 6. Add the following roles to the service account:
	 - Service Account User
	 - Cloud Functions Admin
	 - Pub/Sub Admin
	 - Storage Admin

 7. Click on *Continue*. Then, click on *Create key*. Select *JSON* and then *Create*. Download the JSON file to a secure location in you computer. Click *Done*.

 8. Navigate to *Storage* on the menu. Create a bucket and name it `lithops-data` or similar. Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

9. Edit your cloudbutton config file and add the following keys:

```yaml
    lithops:
        storage: gcp_storage

    gcp:
        project_name : <<PROJECT_ID>>
        service_account : <SERVICE_ACCOUNT_EMAIL>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
        region : <REGION_NAME>

    gcp_storage:
        storage_bucket: <BUCKET_NAME>
```
 
## Summary of configuration keys for Google:

### Google Cloud Platform:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp | project_name | |yes | Project id given by Google Cloud Platform in step 3 (e.g. lithops-876385) |
|gcp | service_account | |yes | Service account email of the service account created on step 5 (e.g. `lithops-executor@lithops.iam.gserviceaccount.com`) |
|gcp | credentials_path | |yes | **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`) |
|gcp | region | |yes | Region of the bucket created at step 8. Functions and pub/sub queue will be created in the same region (e.g. `us-east1`) |

### Google Cloud Storage
|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_storage | storage_bucket | | yes | The name of a bucket that exists in your account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in `lithops` section |
 
