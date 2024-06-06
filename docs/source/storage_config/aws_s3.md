# AWS S3

Lithops with AWS S3 as storage backend.

## Installation

1. Install AWS backend dependencies:

```bash
python3 -m pip install lithops[aws]
```

## Configuration

Lithops automatically creates a bucket with a unique name for your user. If you want to use a different bucket, you can create it manually and provide the name in the lithops config file. For this:

1. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)

2. Navigate to *S3* and *create a bucket*. Type a name (e.g. `lithops-data-mysuer`). The bucket should be created in the same region as the Lambda functions are expected to be run (mainly to avoid inter-region data transfer charges).


## AWS Credential setup

Lithops loads AWS credentials as specified in the [boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html).

In summary, you can use one of the following settings:

1. Provide the credentials via the `~/.aws/config` file, or set the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.

    You can run `aws configure` command if the AWS CLI is installed to setup the credentials. Then set in the Lithops config file:
    ```yaml
    lithops:
        storage: aws_s3

    aws:
        region: <REGION_NAME>
    ```

2. Provide the credentials in the `aws` section of the Lithops config file:
    ```yaml
    lithops:
        storage: aws_s3

    aws:
        access_key_id: <AWS_ACCESS_KEY_ID>
        secret_access_key: <AWS_SECRET_ACCESS_KEY>
        region: <REGION_NAME>
    ```
 
## Summary of configuration keys for AWS:

### AWS:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | region | |yes | AWS Region. For example `us-east-1` |
|aws | access_key_id | |no | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |no | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | session_token | |no | Session token for temporary AWS credentials |

### Summary of configuration keys for AWS S3:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_s3 | region | |no | Region of your Bucket. e.g `us-east-1`, `eu-west-1`, etc. Lithops will use the region set under the `aws` section if it is not set here |
|aws_s3 | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |

