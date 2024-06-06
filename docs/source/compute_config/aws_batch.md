# AWS Batch

Lithops with *AWS Batch* as serverless batch compute backend.

## Installation

1. Install AWS backend dependencies:

```bash
python3 -m pip install lithops[aws]
```

## Configuration

1. [Login](https://console.aws.amazon.com/?nc2=h_m_mc) to Amazon Web Services Console (or signup if you don't have an account)
 
2. Navigate to **IAM > Roles** to create the ECS Task Execution Role. AWS provides a default role named `ecsTaskExecutionRole`, which can be used instead. If you want to create another role or it is missing, create a new role attached to `Elastic Container Service Task`, and add the following policies:
    - `SecretsManagerReadWrite`
    - `AmazonEC2ContainerRegistryFullAccess`
    - `CloudWatchFullAccess`
    - `AmazonECSTaskExecutionRolePolicy`

3. Navigate to **IAM > Roles** to create the ECS Instance Role. AWS provides a default role named `ecsInstanceRole`, which can be used instead. If you want to create another role or it is missing, create a new role attached to `EC2`, and add the following policy:
    - `AmazonEC2ContainerServiceforEC2Role`

4. Navigate to **IAM > Policies**. Click on **Create policy**. If you already created this policy for the AWS Lambda or AWS EC2 backend, jump to step 7.

5. Select **JSON** tab and paste the following JSON policy:
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

6. Click **Next: Tags** and **Next: Review**. Fill the policy name field (you can name it `lithops-policy` or similar) and create the policy.

7. Go back to **IAM** and navigate to **Roles** tab. Click **Create role**.

8. Choose **Elastic Container Service** on the use case list and then click on **Elastic Container Service Task**. Click **Next: Permissions**. Select the policy created before (`lithops-policy`). Click **Next: Tags** and **Next: Review**. Type a role name, for example `ecsTaskJobRole`. Click on **Create Role**.

## AWS Credential setup

Lithops loads AWS credentials as specified in the [boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html).

In summary, you can use one of the following settings:

1. Provide the credentials via the `~/.aws/config` file, or set the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.

    You can run `aws configure` command if the AWS CLI is installed to setup the credentials. Then set in the Lithops config file:
    ```yaml
    lithops:
        backend: aws_batch

    aws_batch:
        region : <REGION_NAME>
        execution_role: <EXECUTION_ROLE_ARN>
        job_role: <JOB_ROLE_ARN>
        subnets:
            - <SUBNET_ID_1>
            - <SUBNET_ID_2>
            - ...
        security_groups:
            - <SECURITY_GROUP_1>
            - ...
    ```

2. Provide the credentials in the `aws` section of the Lithops config file. In this case you can omit setting the `job_role`:
    ```yaml
    lithops:
        backend: aws_batch

    aws:
        access_key_id: <AWS_ACCESS_KEY_ID>
        secret_access_key: <AWS_SECRET_ACCESS_KEY>
        region: <REGION_NAME>

    aws_batch:
        execution_role: <EXECUTION_ROLE_ARN>
        job_role: <JOB_ROLE_ARN>  # Not mandatory if the credentials are in the aws section
        subnets:
            - <SUBNET_ID_1>
            - <SUBNET_ID_2>
            - ...
        security_groups:
            - <SECURITY_GROUP_1>
            - ...
    ```

## Summary of configuration keys for AWS

### AWS

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aws | region | |yes | AWS region name. For example `us-east-1` |
|aws | access_key_id | |no | Account access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | secret_access_key | |no | Account secret access key to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one. |
|aws | session_token | |no | Session token for temporary AWS credentials |
|aws | account_id | |no | *This field will be used if present to retrieve the account ID instead of using AWS STS. The account ID is used to format full image names for container runtimes. |

### AWS Batch

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
| aws_batch  | execution_role   |  | yes | ARN of the execution role used to execute AWS Batch tasks on ECS for Fargate environments |
| aws_batch  | job_role   |  | yes | ARN of the job role used to execute AWS Batch tasks on ECS for Fargate environments. Not mandatory if the credentials are in the `aws` section of the configuration|
| aws_batch  | security_groups  |  | yes | List of Security groups to attach for ECS task containers. By default, you can use a security group that accepts all outbound traffic but blocks all inbound traffic. |
| aws_batch  | subnets          |  | yes | List of subnets from a VPC where to deploy the ECS task containers. Note that if you are using a **private subnet**, you can set `assign_public_ip` to `false` but make sure containers can reach other AWS services like ECR, Secrets service, etc., by, for example, using a NAT gateway. If you are using a **public subnet** you must set `assign_public_up` to `true` |
| aws_batch  | instance_role    |  | no | ARN of the execution role used to execute AWS Batch tasks on ECS for EC2 environments. Mandatory if using the **EC2** or **SPOT** `env_type` |
| aws_batch  | region      |  | no | Region name (like `us-east-1`) where to deploy the ECS cluster. Lithops will use the region set under the `aws` section if it is not set here |
| aws_batch  | assign_public_ip | `true` | no | Assign public IPs to ECS task containers. Set to `true` if the tasks are being deployed in a public subnet. Set to `false` when deploying on a private subnet. |
| aws_batch  | runtime          |  | no | Container runtime name in ECR. If not provided Lithops will automatically build a default runtime |
| aws_batch  | runtime_timeout  | 180 | no | Runtime timeout managed by the cloud provider. |
| aws_batch  | runtime_memory   | 1024 | no | Runtime memory assigned to each task container. |
| aws_batch  | runtime_cpu      | 0.5 | no | Number of vCPUs assigned to each task container. It can be different from `worker_processes`. |
| aws_batch  | worker_processes | 1 | no |  Number of parallel Lithops processes in a worker. This is used to parallelize function activations within the worker. |
| aws_batch  | service_role     | | no | Service role for AWS Batch. Leave empty to use a service-linked execution role. More info [here](https://docs.aws.amazon.com/batch/latest/userguide/using-service-linked-roles.html) |
| aws_batch  | env_max_cpus     | 10 | no | Maximum total CPUs of the compute environment  |
| aws_batch  | env_type         | FARGATE_SPOT | no | Compute environment type, one of: `["EC2", "SPOT", "FARGATE", "FARGATE_SPOT"]` |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b aws_batch -s aws_s3
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```
