# Lithops on AWS Lambda

Lithops with *AWS Lambda* as serverless compute backend.

### Installation

1. Install Amazon Web Services backend dependencies:

```
$ python3 -m pip install lithops[aws]
```

2. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)
 
3. Navigate to *IAM > Roles*. Click on *Create Role*.
 
4. Select *Lambda* and then click *Next: Permissions*.
 
5. Type `s3` at the search bar and select *AmazonS3FullAccess*. Type `lambda` at the search bar and select *AWSLambdaFullAccess*. Click on *Next: Tags* and then *Next: Review*.
 
6. Type a role name, for example `lithops-execution-role`. Click on *Create Role*.

### Configuration

6. Edit your lithops config and add the following keys:

```yaml
    serverless:
        backend: aws_lambda

    aws:
        access_key_id: <ACCESS_KEY_ID>
        secret_access_key: <SECRET_ACCESS_KEY>

    aws_lambda:
        execution_role: <EXECUTION_ROLE_ARN>
        region_name: <REGION_NAME>
```

 - `access_key_id` and `secret_access_key`: Account access keys to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.
 - `region_name`: Region where the S3 bucket is located and where Lambda functions will be invoked (e.g. `us-east-1`).
 - `execution_role`: ARN of the execution role created at step 3. You can find it in the Role page at the *Roles* list in the *IAM* section (e.g. `arn:aws:iam::1234567890:role/lithops-role`).
 - `runtime`: Runtime name already deployed in the service
 
#### Additional configuration

##### VPC
To connect the Lithops lambda to a VPC, add the following configuration to the `aws_lambda` configuration section:

```yaml
    aws_lambda:
        execution_role: <EXECUTION_ROLE_ARN>
        region_name: <REGION_NAME>
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

**Note:** To be able to create netwrok interfaces for Lambda functions, the role created in step 3 has to have permissions to do so, for example by adding the permission *EC2FullAccess*.

For more information, check out [AWS documentation on VPCs](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html).

##### EFS
To attach EFS volumes to the Lithops lambda, add the following configuration to the `aws_lambda` configuration section:

```yaml
    aws_lambda:
        execution_role: <EXECUTION_ROLE_ARN>
        region_name: <REGION_NAME>
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

