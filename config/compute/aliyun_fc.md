# Lithops on Alibaba Cloud (Aliyun)

Lithops with *Aliyun Function Compute* as serverless compute backend.

### Configuration

1. Install Alibaba Cloud backend dependencies:

```
$ python3 -m pip install lithops[aliyun]
```

2. Edit your Lithops config and add the following keys:

```yaml
  serverless:
    backend : aliyun_fc

  aliyun_fc:
    public_endpoint : <PUBLIC_ENDPOINT>
    access_key_id : <ACCESS_KEY_ID>
    access_key_secret : <ACCESS_KEY_SECRET>
```

   - `public_endpoint`: public endpoint (URL) to the service. OSS and FC endpoints are different.
   - `access_key_id`: Access Key Id.
   - `access_key_secret`: Access Key Secret. 
   - `runtime`: Runtime name already deployed in the service
