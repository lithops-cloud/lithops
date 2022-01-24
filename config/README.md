# Lithops configuration

By default Lithops works on Localhost if no configuration is provided. To run workloads on the Cloud, you must configure both a compute and a storage backend. Failing to configure them properly will prevent Lithops to submit workloads. Lithops configuration can be provided either in a configuration file or in runtime via a Python dictionary. 

### Configuration file

To configure Lithops through a [configuration file](config_template.yaml) you have multiple options:

1. Create a new file called `config` in the `~/.lithops` folder.

2. Create a new file called `.lithops_config` in the root directory of your project from where you will execute your Lithops scripts.

3. Create the config file in any other location and configure the `LITHOPS_CONFIG_FILE` system environment variable:

	 	LITHOPS_CONFIG_FILE=<CONFIG_FILE_LOCATION>
    
### Configuration keys in runtime

An alternative mode of configuration is to use a python dictionary. This option allows to pass all the configuration details as part of the Lithops invocation in runtime. An entire list of sections and keys is [here](config_template.yaml)

## Compute and Storage backends
Choose your compute and storage engines from the table below


<table>
<tr>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
Standalone Compute Backends
</small>
</p>
</th>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
Serverless Compute Backends
</small>
</p>
</th>
<th align="center">
<img width="441" height="1">
<p> 
<small>
Storage Backends
</small>
</p>
</th>
</tr>
<tr>
<td>

- [Localhost](../docs/source/compute_config/localhost.md)
- [Remote Virtual Machine](../docs/source/compute_config/vm.md)
- [IBM Virtual Private Cloud](../docs/source/compute_config/ibm_vpc.md)
- [AWS Elastic Compute Cloud (EC2)](../docs/source/compute_config/aws_ec2.md)

</td>
<td>

- [IBM Cloud Functions](../docs/source/compute_config/ibm_cf.md)
- [IBM Code Engine](../docs/source/compute_config/code_engine.md)
- [Kubernetes Jobs](../docs/source/compute_config/k8s_job.md)
- [Knative](../docs/source/compute_config/knative.md)
- [OpenWhisk](../docs/source/compute_config/openwhisk.md)
- [AWS Lambda](../docs/source/compute_config/aws_lambda.md)
- [AWS Batch](../docs/source/compute_config/aws_batch.md)
- [Google Cloud Functions](../docs/source/compute_config/gcp_functions.md)
- [Google Cloud Run](../docs/source/compute_config/gcp_cloudrun.md)
- [Azure Functions](../docs/source/compute_config/azure_functions.md)
- [Aliyun functions](../docs/source/compute_config/aliyun_functions.md)

</td>
<td>

- [IBM Cloud Object Storage](../docs/source/storage_config/ibm_cos.md)
- [AWS S3](../docs/source/storage_config/aws_s3.md)
- [Google Cloud Storage](../docs/source/storage_config/gcp_storage.md)
- [Azure Blob Storage](../docs/source/storage_config/azure_blob.md)
- [Aliyun Object Storage Service](../docs/source/storage_config/aliyun_oss.md)
- [Infinispan](../docs/source/storage_config/infinispan.md)
- [Ceph](../docs/source/storage_config/ceph.md)
- [MinIO](../docs/source/storage_config/minio.md)
- [Redis](../docs/source/storage_config/redis.md)
- [OpenStack Swift](../docs/source/storage_config/swift.md)

</td>
</tr>
</table>

## Verify

Test if Lithops is working properly:

### Using Lithops configuration file

```python
import lithops

def hello_world(name):
    return 'Hello {}!'.format(name)

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(hello_world, 'World')
    print(fexec.get_result())
```

### Providing configuration in runtime
Example of providing configuration keys for IBM Cloud Functions and IBM Cloud Object Storage

```python
import lithops

config = {'lithops': {'backend': 'ibm_cf', 'storage': 'ibm_cos'},

          'ibm_cf':  {'endpoint': 'ENDPOINT',
                      'namespace': 'NAMESPACE',
                      'api_key': 'API_KEY'},

          'ibm_cos': {'storage_bucket': 'BUCKET_NAME',
                      'region': 'REGION',
                      'api_key': 'API_KEY'}}

def hello_world(name):
    return 'Hello {}!'.format(name)

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor(config=config)
    fexec.call_async(hello_world, 'World')
    print(fexec.get_result())
```

## Summary of configuration keys for Lithops

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|lithops | backend | ibm_cf | no | Compute backend implementation. IBM Cloud Functions is the default |
|lithops | storage | ibm_cos | no | Storage backend implementation. IBM Cloud Object Storage is the default |
|lithops | data_cleaner | True | no |If set to True, then the cleaner will automatically delete all the temporary data that was written into `storage_bucket/lithops.jobs`|
|lithops | monitoring | storage | no | Monitoring system implementation. One of: **storage** or **rabbitmq** |
|lithops | monitoring_interval | 2 | no | Monitoring check interval in seconds in case of **storage** monitoring |
|lithops | data_limit | 4 | no | Max (iter)data size (in MB). Set to False for unlimited size |
|lithops | execution_timeout | 1800 | no | Functions will be automatically killed if they exceed this execution time (in seconds). Alternatively, it can be set in the `call_async()`, `map()` or `map_reduce()` calls using the `timeout` parameter.|
|lithops | include_modules | [] | no | Explicitly pickle these dependencies. All required dependencies are pickled if default empty list. No one dependency is pickled if it is explicitly set to None |
|lithops | exclude_modules | [] | no | Explicitly keep these modules from pickled dependencies. It is not taken into account if you set include_modules |
|lithops | log_level | INFO |no | Logging level. One of: WARNING, INFO, DEBUG, ERROR, CRITICAL, Set to None to disable logging |
|lithops | log_format | "%(asctime)s [%(levelname)s] %(name)s -- %(message)s" |no | Logging format string |
|lithops | log_stream | ext://sys.stderr |no | Logging stream. eg.: ext://sys.stderr,  ext://sys.stdout|
|lithops | log_filename |  |no | Path to a file. log_filename has preference over log_stream. |
|lithops | customized_runtime | False | no | Enables to build a new runtime with the map() function and its dependencies integrated. Only docker-based backends support this feature. |
