# Lithops on Alibaba Cloud (Aliyun)

Lithops with *Aliyun Function Compute* as serverless compute backend.

### Configuration

1. Install Alibaba Cloud backend dependencies:

```
$ python3 -m pip install lithops[aliyun]
```

2. Edit your Lithops config and add the following keys:

```yaml
  lithops:
      backend : aliyun_fc

  aliyun_fc:
      public_endpoint : <PUBLIC_ENDPOINT>
      access_key_id : <ACCESS_KEY_ID>
      access_key_secret : <ACCESS_KEY_SECRET>
```

    
### Summary of configuration keys for Alibaba Functions Compute:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|aliyun_fc | public_endpoint | |yes | public endpoint (URL) to the service. OSS and FC endpoints are different. |
|aliyun_fc | access_key_id | |yes |  Account access key to Alibaba services. |
|aliyun_fc | access_key_secret |  | yes | Account secret access key to Alibaba services.|
|aliyun_fc | runtime |  |no | Docker image name.|
|aliyun_fc | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|aliyun_fc | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|aliyun_fc | invoke_pool_threads | 500 |no | Number of concurrent threads used for invocation |
