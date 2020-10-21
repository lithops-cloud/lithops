# Lithops on GCP Functions

Lithops with *GCP Functions* as serverless compute backend.

### Installation

1. Install Google Cloud Platform backend dependencies:

```
$ pip install lithops[gcp]
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

### Configuration

1. Edit your lithops config and add the following keys:

```yaml
    serverless:
        backend: gcp_functions

    gcp:
        project_name : <PROJECT_NAME>
        service_account : <SERVICE_ACCOUNT_EMAIL>
        credentials_path : <FULL_PATH_TO_CREDENTIALS_JSON>
        region : <REGION_NAME>
```

 - `project_name`: Project name introduced in step 3 (e.g. `lithops`)
 - `service_account`: Service account email of the service account created on step 5 (e.g. `lithops-executor@lithops.iam.gserviceaccount.com`)
 - `credentials_path`: **Absolute** path of your JSON key file downloaded in step 7 (e.g. `/home/myuser/lithops-invoker1234567890.json`)
 - `region`: Region of the bucket created at step 8. Functions and pub/sub queue will be created in the same region (e.g. `us-east1`)
