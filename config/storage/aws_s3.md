# Lithops on AWS S3

Lithops with AWS S3 as storage backend.

### Installation

1. Install Amazon Web Services backend dependencies:

```
$ pip install lithops[aws]
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
        endpoint : <S3_ENDPOINT_URI>
```

 - `access_key_id` and `secret_access_key`: Account access keys to AWS services. To find them, navigate to *My Security Credentials* and click *Create Access Key* if you don't already have one.
 - `endpoint`: Endpoint URL of the bucket (e.g. `https://s3.us-east-1.amazonaws.com`)
