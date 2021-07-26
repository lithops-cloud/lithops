# Lithops on AWS S3

Lithops with AWS S3 as storage backend.

### Installation

1. Install Amazon Web Services backend dependencies:

    ```
    $ python3 -m pip install lithops[aws]
    ```

2. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)

3. Navigate to *S3* and *create a bucket*. Type a name (e.g. `lithops-data`). The bucket should be created in the same region as the Lambda functions are expected to be run (mainly to avoid inter-region data transfer charges).


### Configuration

4. Edit your lithopsa config and add the following keys:

    ```yaml
    lithops:
        storage: aws_s3

    aws:
        access_key_id : <ACCESS_KEY_ID>
        secret_access_key : <SECRET_ACCESS_KEY>

    aws_s3:
        storage_bucket: <BUCKET_NAME>
        region_name : <S3_BUCKET_REGION>
    ```

 
### Summary of configuration keys for AWS:

#### AWS:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | access_key_id | |yes | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |yes | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |

#### Summary of configuration keys for AWS S3:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_s3 | storage_bucket | | yes | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in `lithops` section |
|aws_s3 | region_name | |yes | region of your Bcuket. e.g us-east-1, eu-west-1, etc |
|aws_s3 | endpoint | |yes | Endpoint to your Bcuket. Make sure to use the full path with 'https://' as prefix. e.g. `https://s3.us-east-1.amazonaws.com` |
