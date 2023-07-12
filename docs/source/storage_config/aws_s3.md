# AWS S3

Lithops with AWS S3 as storage backend.

## Installation

1. Install Amazon Web Services backend dependencies:

    ```
    $ python3 -m pip install lithops[aws]
    ```

2. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)

3. Navigate to *S3* and *create a bucket*. Type a name (e.g. `lithops-data`). The bucket should be created in the same region as the Lambda functions are expected to be run (mainly to avoid inter-region data transfer charges).


## Configuration

4. Edit your lithopsa config and add the following keys:

    ```yaml
    lithops:
        storage: aws_s3

    aws:
        region : <REGION_NAME>
        access_key_id : <ACCESS_KEY_ID>
        secret_access_key : <SECRET_ACCESS_KEY>
    ```

## AWS Credential setup

Lithops loads AWS credentials as specified in the [boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html).

In summary, you can use the following settings:

1. Provide credentials via the `~/.aws/config` file. **This is the preferred option to configure AWS credentials for use with Lithops**:

    You can run `aws configure` command if the AWS CLI is installed to setup the credentials.

2. Provide credentials via environment variables:

    Lithops needs at least `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_DEFAULT_REGION` environment variables set.

3. Provide the credentials in the `aws` section of the Lithops config file **This option is not ideal and will be removed in future Lithops releases!**:
```yaml
lithops:
    storage: aws_s3

aws:
    access_key_id: <AWS_ACCESS_KEY_ID>
    secret_access_key: <AWS_SECRET_ACCESS_KEY>
    region: <REGION_NAME>
```

### Setup for SSO-based users

Users using SSO-based accounts do not require an IAM user, and have temporal session access tokens instead. To configure access to SSO-based accounts, you can configure a profile in the `~/.aws/config` file for using SSO authentication:

```yaml
[profile my-sso-profile]
sso_start_url = https://XXXXXXXX.awsapps.com/start
sso_region = us-east-1
sso_account_id = XXXXXXXXXXX
sso_role_name = XXXXXXXXXXXXXXXXX
region = us-east-1
```

Then, you can log in or refresh your credentials by using the sso login command:

```
$ aws sso login --profile my-sso-profile
```

To use this profile, you must specify it in the `aws` section of the Lithops config file:

```yaml
lithops:
    storage: aws_s3

aws:
    config_profile: my-sso-profile
```

 
## Summary of configuration keys for AWS:


### AWS S3

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws_s3 | region | |no | Region of your Bcuket. e.g `us-east-1`, `eu-west-1`, etc. Lithops will use the region set under the `aws` section if it is not set here |
|aws_s3 | storage_bucket | | no | The name of a bucket that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |

### AWS

|Group| Key               | Default  | Mandatory | Additional info                                                                                                                                                    |
|---|-------------------|----------|-----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|aws | region            |          | yes       | AWS Region. For example `us-east-1`                                                                                                                                |
|aws | config_profile    | "default" | no        | AWS SDK [configuration profile](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html#using-a-configuration-file) name.                 |
|aws | access_key_id     |          | no        | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.               |
|aws | secret_access_key |          | no         | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.        |
|aws | session_token     |          | no        | Session token for temporary AWS credentials                                                                                                                        |
|aws | account_id        |          | no        | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |

