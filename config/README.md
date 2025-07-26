# Lithops configuration

By default Lithops works on Localhost if no configuration is provided. To run workloads on the Cloud, you must configure both a compute and a storage backend. Failing to configure them properly will prevent Lithops to submit workloads. Lithops configuration can be provided either in a configuration file or in runtime via a Python dictionary. 

### Configuration file

To configure Lithops through a [configuration file](config_template.yaml) you have multiple options:

1. Create a new file called `config` in the `~/.lithops` folder (i.e: `~/.lithops/config`).

2. Create a new file called `.lithops_config` in the root directory of your project from where you will execute your Lithops scripts.

3. Create a new file called `config` in the `/etc/lithops/` folder (i.e: `/etc/lithops/config`). Useful for sharing the config file on multi-user machines.

4. Create the config file in any other location and configure the `LITHOPS_CONFIG_FILE` system environment variable:

	 	LITHOPS_CONFIG_FILE=<CONFIG_FILE_LOCATION>
    
### Configuration keys in runtime

An alternative mode of configuration is to use a python dictionary. This option allows to pass all the configuration details as part of the Lithops invocation in runtime. An entire list of sections and keys is [here](config_template.yaml)

## Compute and Storage backends
Choose your compute and storage engines from the table below

<table>
<tr>
<th align="center">
<p> 
<small>
Compute Backends
</small>
</p>
</th>
	
<th align="center">
<p> 
<small>
Storage Backends
</small>
</p>
</th>
</tr>

<tr>
<td valign="top">

- [Localhost](../docs/source/compute_config/localhost.md)

<b>Serverless (FaaS) Backends:</b>
- [AWS Lambda](../docs/source/compute_config/aws_lambda.md)
- [Google Cloud Functions](../docs/source/compute_config/gcp_functions.md)
- [Azure Functions](../docs/source/compute_config/azure_functions.md)
- [Aliyun Functions](../docs/source/compute_config/aliyun_functions.md)
- [Oracle Cloud Functions](../docs/source/compute_config/oracle_functions.md)
- [OpenWhisk](../docs/source/compute_config/openwhisk.md)

<b>Serverless (CaaS) Backends:</b>
- [IBM Code Engine](../docs/source/compute_config/code_engine.md)
- [AWS Batch](../docs/source/compute_config/aws_batch.md)
- [Google Cloud Run](../docs/source/compute_config/gcp_cloudrun.md)
- [Azure Container APPs](../docs/source/compute_config/azure_containers.md)
- [Kubernetes](../docs/source/compute_config/kubernetes.md)
- [Knative](../docs/source/compute_config/knative.md)
- [Singularity](../docs/source/compute_config/singularity.md)

<b>Standalone Backends:</b>
- [Virtual Machine](../docs/source/compute_config/vm.md)
- [IBM Virtual Private Cloud](../docs/source/compute_config/ibm_vpc.md)
- [AWS Elastic Compute Cloud (EC2)](../docs/source/compute_config/aws_ec2.md)
- [Azure Virtual Machines](../docs/source/compute_config/azure_vms.md)

</td>
<td valign="top">

- [Localhost](../docs/source/compute_config/localhost.md)
	</p>
<b>Object Storage:</b>
- [IBM Cloud Object Storage](../docs/source/storage_config/ibm_cos.md)
- [AWS S3](../docs/source/storage_config/aws_s3.md)
- [Google Cloud Storage](../docs/source/storage_config/gcp_storage.md)
- [Azure Blob Storage](../docs/source/storage_config/azure_blob.md)
- [Aliyun Object Storage Service](../docs/source/storage_config/aliyun_oss.md)
- [Oracle Cloud Object Storage](../docs/source/storage_config/oracle_oss.md)
- [Ceph](../docs/source/storage_config/ceph.md)
- [MinIO](../docs/source/storage_config/minio.md)
- [OpenStack Swift](../docs/source/storage_config/swift.md)
	</p>
<b>In-Memory Storage:</b>
- [Redis](../docs/source/storage_config/redis.md)
- [Infinispan](../docs/source/storage_config/infinispan.md)

</td>
</tr>
</table>

## Verify

Test if Lithops is working properly:

### Using Lithops configuration file

```python
import lithops

def hello_world(name):
    return f'Hello {name}!'

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(hello_world, 'World')
    print(fexec.get_result())
```

### Providing configuration in runtime
Example of providing configuration keys for IBM Code Engine and IBM Cloud Object Storage

```python
import lithops

config = {
    'lithops': {
        'backend': 'code_engine',
        'storage': 'ibm_cos'
    },
    'ibm': {
        'region': 'REGION',
        'iam_api_key': 'IAM_API_KEY',
        'resource_group_id': 'RESOURCE_GROUP_ID'
    },
    'ibm_cos': {
        'storage_bucket': 'STORAGE_BUCKET'
    }
}

def hello_world(number):
    return f'Hello {number}!'

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor(config=config)
    fexec.map(hello_world, [1, 2, 3, 4])
    print(fexec.get_result())
```

## Summary of configuration keys for Lithops

| Group   | Key                 | Default      | Mandatory | Additional info                                                                                     |
|---------|---------------------|--------------|-----------|--------------------------------------------------------------------------------------------------|
| lithops | backend             | aws_lambda   | no        | Compute backend implementation. `localhost` is the default if no config or config file is provided. |
| lithops | storage             | aws_s3       | no        | Storage backend implementation. `localhost` is the default if no config or config file is provided. |
| lithops | data_cleaner        | True         | no        | If True, automatically deletes temporary data written to `storage_bucket/lithops.jobs`.          |
| lithops | monitoring          | storage      | no        | Monitoring system implementation. Options: **storage** or **rabbitmq**.                           |
| lithops | monitoring_interval | 2            | no        | Interval in seconds for monitoring checks when using **storage** monitoring.                      |
| lithops | data_limit          | 4            | no        | Maximum size (in MB) for iterator data chunks. Set to False for unlimited size.                   |
| lithops | execution_timeout   | 1800         | no        | Maximum execution time in seconds for functions. Functions exceeding this time are terminated. Can also be set per call via the `timeout` parameter. |
| lithops | include_modules     | []           | no        | List of dependencies to explicitly include for pickling. If empty, all required dependencies are included. If set to None, no dependencies are included. |
| lithops | exclude_modules     | []           | no        | List of dependencies to exclude from pickling. Ignored if `include_modules` is set.              |
| lithops | log_level           | INFO         | no        | Logging level. Options: WARNING, INFO, DEBUG, ERROR, CRITICAL. Set to None to disable logging.    |
| lithops | log_format          | "%(asctime)s [%(levelname)s] %(name)s -- %(message)s" | no | Format string for log messages.                                                                    |
| lithops | log_stream          | ext://sys.stderr | no     | Logging output stream, e.g., ext://sys.stderr or ext://sys.stdout.                                |
| lithops | log_filename        | (empty)      | no        | File path for logging output. Overrides `log_stream` if set.                                     |
| lithops | retries             | 0            | no        | Number of retries for failed function invocations. Default is 3. Can be overridden per API call. |
