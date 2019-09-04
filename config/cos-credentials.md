# Credentials for IBM Cloud Object Storage

 - Login to IBM Cloud and open up your dashboard.
 - Make sure you select 'All Resources' under Resource Group. and navigate to your instance of Object Storage.
 - In the side navigation, click `Endpoints` to find your endpoint.
 - In the side navigation, click `Service Credentials`.
 - Click `New credential +` and provide the necessary information.
 - Click `Add` to generate service credential.
 - Click `View credentials` and copy the *apikey* value.

Alternative usage is to use the `ACCESS_KEY` and the `SECRET_KEY` instead of the `<COS_API_KEY>`.
To generate the `ACCESS_KEY` and the `SECRET_KEY` follow these steps:
 - In the side navigation, click `Service Credentials`.
 - Click `New credential +` and provide the necessary information. To generate HMAC credentials, specify the following in the Add Inline Configuration Parameters (Optional) field: {"HMAC":true}
 - Click `Add` to generate service credential.
 - Click `View credentials` and copy the *access_key_id* and the *secret_access_key* values.
