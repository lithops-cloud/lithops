# AWS Lambda

Lithops with *AWS Lambda* as serverless compute backend.

## Installation

1. Install Amazon Web Services backend dependencies:

```
python3 -m pip install lithops[aws]
```

2. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)
 
3. Navigate to **IAM > Policies**. Click on **Create policy**.

4. Select **JSON** tab and paste the following JSON policy:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:*",
                "lambda:*",
                "ec2:*",
                "ecr:*",
                "sts:GetCallerIdentity",
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "*"
        }
    ]
}
```

5. Click **Next: Tags** and **Next: Review**. Fill the policy name field (you can name it `lithops-policy` or simmilar) and create the policy.

6. Go back to **IAM** and navigate to **Roles** tab. Click **Create role**.

7. Choose **Lambda** on the use case list and click **Next: Permissions**. Select the policy created before (`lithops-policy`). Click **Next: Tags** and **Next: Review**. Type a role name, for example `lithops-execution-role`. Click on *Create Role*.

## Configuration

6. Edit your lithops config and add the following keys:

```yaml
lithops:
    backend: aws_lambda

aws_lambda:
    execution_role: <EXECUTION_ROLE_ARN>
    region: <REGION_NAME>
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
    backend: aws_lambda

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
    backend: aws_lambda

aws:
    config_profile: my-sso-profile
```

More info [here](https://docs.aws.amazon.com/cli/latest/userguide/sso-configure-profile-token.html).


## Summary of configuration keys for AWS Lambda

### AWS Lambda

| Group      | Key                 | Default | Mandatory | Additional info                                                                                                                                                                    |
|------------|---------------------|---------|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| aws_lambda | execution_role      |         | yes       | ARN of the execution role created at step 3. You can find it in the Role page at the *Roles* list in the *IAM* section (e.g. `arn:aws:iam::1234567890:role/lithops-execution-role` |
| aws_lambda | region         |         | no       | Region where the S3 bucket is located and where Lambda functions will be invoked (e.g. `us-east-1`). Lithops will use the `region` set under the `aws` section if it is not set here |
| aws_lambda | max_workers         | 1000    | no        | Max number of workers per `FunctionExecutor()`                                                                                                                                     |
| aws_lambda | worker_processes    | 1       | no        | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker                                                            |
| aws_lambda | runtime             |         | no        | Docker image name                                                                                                                                                                  |
| aws_lambda | runtime_memory      | 256     | no        | Memory limit in MB. Default 256MB                                                                                                                                                  |
| aws_lambda | runtime_timeout     | 180     | no        | Runtime timeout in seconds. Default 3 minutes                                                                                                                                      |
| aws_lambda | invoke_pool_threads | 64      | no        | Number of concurrent threads used for invocation                                                                                                                                   |
| aws_lambda | remote_invoker      | False   | no        | Activate the remote invoker feature that uses one cloud function to spawn all the actual `map()` activations                                                                       |
| aws_lambda | architecture        | x86_64  | no        | Runtime architecture. One of **x86_64** or **arm64**                                                                                                                               |
| aws_lambda | ephemeral_storage   | 512     | no         | Ephemeral storage (`/tmp`) size in MB (must be between 512 MB and 10240 MB)                                                                                                        |
| aws_lambda | env_vars   | {}      | no         | List of {name: ..., value: ...} pairs for Lambda instance environment variables                                                                                                    |
 
### AWS

|Group| Key               | Default  | Mandatory | Additional info                                                                                                                                                    |
|---|-------------------|----------|-----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|aws | region            |          | yes       | AWS Region. For example `us-east-1`                                                                                                                                |
|aws | config_profile    | "default" | no        | AWS SDK [configuration profile](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html#using-a-configuration-file) name.                 |
|aws | access_key_id     |          | no        | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.               |
|aws | secret_access_key |          | no         | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.        |
|aws | session_token     |          | no        | Session token for temporary AWS credentials                                                                                                                        |
|aws | account_id        |          | no        | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |


## Additional configuration

### VPC
To connect the Lithops lambda to a VPC, add the following configuration to the `aws_lambda` configuration section:

```yaml
aws_lambda:
    execution_role: <EXECUTION_ROLE_ARN>
    region: <REGION_NAME>
    vpc:
        subnets:
            - <SUBNET_ID_1>
            - <SUBNET_ID_2>
            ...
        security_groups:
            - <SECURITY_GROUP_1>
            - <SECURITY_GROUP_2>
                ...
```

- `subnets`: A list of VPC subnet IDs.
- `security_groups`: A list of VPC security groups IDs.

**Note:** To be able to create network interfaces for Lambda functions, the role created in step 3 has to have permissions to do so, for example by adding the permission *EC2FullAccess*.

For more information, check out [AWS documentation on VPCs](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html).

### EFS
To attach EFS volumes to the Lithops lambda, add the following configuration to the `aws_lambda` configuration section:

```yaml
aws_lambda:
    execution_role: <EXECUTION_ROLE_ARN>
    region: <REGION_NAME>
    vpc:
        ...
    efs:
        - access_point: <EFS_ACCESS_POINT_1>
          mount_path: <LAMBDA_VOLUME_MOUNT_PATH_1>
        - access_point: <EFS_ACCESS_POINT_2>
          mount_path: <LAMBDA_VOLUME_MOUNT_PATH_2>
            ...
```

- `access_point`: The Amazon Resource Name (ARN) of the Amazon EFS access point that provides access to the file system.
- `mount_path`: The path where the function can access the file system. It **must** start with `/mnt`.

**Note:** to access those volumes, the Lithops lambda has to be connected to the same VPC and subnets as the EFS volumes are mounted to.

For more information, check out [AWS documentation on attaching EFS volumes to Lambda](https://aws.amazon.com/blogs/compute/using-amazon-efs-for-aws-lambda-in-your-serverless-applications/).


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops test -b aws_lambda -s aws_s3
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```