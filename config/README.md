# Choose your compute and storage backend

Lithops can work with almost any compute backend and storage any can be used with almost any cloud provider. You have multiple options to choose compute backend and storage backend based on your needs. 

After you choose your compute and storage engine, you need to configure Lithops so it can use choosen compute and storage. Lithops configuration can be provided either in configuration file or provided in runtime via Python dictionary. 

## Lithops configuration

### Configuration file

To configure Lithops through a [configuration template file](config_template.yaml) you have multiple options:

1. Create e new file called `config` in the `~/.lithops` folder.

2. Create a new file called `.lithops_config` in the root directory of your project from where you will execute your Lithops scripts.

3. Create the config file in any other location and configure the `LITHOPS_CONFIG_FILE` system environment variable:


	 	LITHOPS_CONFIG_FILE=<CONFIG_FILE_LOCATION>
    
### Configuration keys in runtime

An alternative mode of configuration is to use a python dictionary. This option allows to pass all the configuration details as part of the Lithops invocation in runtime. An entire list of sections and keys is [here](config_template.yaml)

## Compute and Storage backends
Choose your compute and storage engine from the table below


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

- [Remote Virtual Machine](compute/remote_vm.md)
- [IBM Virtual Private Cloud](compute/ibm_vpc.md)

</td>
<td>

- [IBM Cloud Functions](compute/ibm_cf.md)
- [IBM Code Engine](compute/code_engine.md)
- [Knative](compute/knative.md)
- [OpenWhisk](compute/openwhisk.md)
- [AWS Lambda](compute/aws_lambda.md)
- [Google Cloud Functions](compute/gcp_functions.md)
- [Google Cloud Run](compute/gcp_run.md)
- [Azure Functions](compute/azure_fa.md)
- [Aliyun functions](compute/aliyun_fc.md)

</td>
<td>

- [IBM Cloud Object Storage](storage/ibm_cos.md)
- [AWS S3](storage/aws_s3.md)
- [Google Cloud Storage](storage/gcp_storage.md)
- [Azure Blob Storage](storage/azure_blob.md)
- [Aliyun Object Storage Service](storage/aliyun_oss.md)
- [Infinispan](storage/infinispan.md)
- [Ceph](storage/ceph.md)
- [Redis](storage/redis.md)
- [OpenStack Swift](storage/swift.md)

</td>
</tr>
</table>

### Lithops and IBM Cloud 
Students or academic stuff are welcome to follow [IBM Academic Initiative](https://ibm.biz/academic), a special program that allows free trial of IBM Cloud for Academic institutions. This program is provided for students and faculty staff members, and allow up to 12 months of free usage. You can register your university email and get a free of charge account.

## Verify

Test if Lithops is working properly:

### Using Lithops configuration file

```python
import lithops

def hello_world(name):
    return 'Hello {}!'.format(name)

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    fexec.call_async(hello, 'World')
    print(fexec.get_result())
```

### Providing configuration in runtime
Example of providing configuration keys for IBM Cloud Functions and IBM Cloud Object Storage

```python
import lithops

config = {'lithops' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'ENDPOINT',
                      'namespace': 'NAMESPACE',
                      'api_key': 'API_KEY'},

          'ibm_cos': {'region': 'REGION',
                      'api_key': 'API_KEY'}}

def hello_world(name):
    return 'Hello {}!'.format(name)

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor(config=config)
    fexec.call_async(hello, 'World')
    print(fexec.get_result())
```

## Using RabbitMQ to monitor function activations (optional)

By default, Lithops uses the storage backend to monitor function activations: Each function activation stores a file named *{id}/status.json* to the Object Storage when it finishes its execution. This file contains some statistics about the execution, including if the function activation ran successfully or not. Having these files, the default monitoring approach is based on polling the Object Store each X seconds to know which function activations have finished and which not.

As this default approach can slow-down the total application execution time, due to the number of requests it has to make against the object store, in Lithops we integrated a RabbitMQ service to monitor function activations in real-time. With RabbitMQ, the content of the *{id}/status.json* file is sent trough a queue. This speeds-up total application execution time, since Lithops only needs one connection to the messaging service to monitor all function activations. We currently support the AMQP protocol. To enable Lithops to use this service, add the *AMQP_URL* key into the *rabbitmq* section in the configuration, for example:

```yaml
rabbitmq:
    amqp_url: <AMQP_URL>  # amqp://
```

In addition, activate the monitoring service by setting *rabbitmq_monitor : True* in the configuration (Lithops section):

```yaml
lithops:
   rabbitmq_monitor: True
```

or in the executor by:

```python
fexec = lithops.FunctionExecutor(rabbitmq_monitor=True)
```


## Summary of configuration keys for Lithops

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|lithops|storage_bucket | |no | Any bucket that exists in your COS account. This will be used by Lithops for intermediate data |
|lithops | storage | ibm_cos | no | Storage backend implementation. IBM Cloud Object Storage is the default |
|lithops| data_cleaner | True | no |If set to True, then the cleaner will automatically delete all the temporary data that was written into `storage_bucket/lithops.jobs`|
|lithops | executor | serverless | no | Execution mode. One of: **localhost**, **serverless** or **standalone** |
|lithops | rabbitmq_monitor | False | no | Activate the rabbitmq monitoring feature |
|lithops | workers | Depends on the compute backend | no | Max number of concurrent workers |
|lithops| data_limit | 4 | no | Max (iter)data size (in MB). Set to False for unlimited size |
|lithops| execution_timeout | 1800 | no | Functions will be automatically killed if they exceed this execution time (in seconds). Alternatively, it can be set in the `call_async()`, `map()` or `map_reduce()` calls with the `timeout` parameter.|
|lithops| include_modules | [] | no | Explicitly pickle these dependencies. All required dependencies are pickled if default empty list. No one dependency is pickled if it is explicitly set to None |
|lithops| exclude_modules | [] | no | Explicitly keep these modules from pickled dependencies. It is not taken into account if you set include_modules |

## Summary of configuration keys for Serverless

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|serverless | backend | ibm_cf |no | Serverless compute backend implementation. IBM Cloud Functions is the default |
|serverless | runtime | Depends on the backend | no | Runtime name to run the functions. |
|serverless | runtime_memory | 256 | no | Default runtime memory (in MB) |
|serverless | runtime_timeout | 600 | no |  Default serveless backend runtime timeout (in seconds) |
|serverless | remote_invoker | False | no |  Activate the remote invoker feature that uses one cloud function to spawn all the actual `map()` activations |
|serverless | customized_runtime | False | no | Enables early preparation of Lithops workers with the map function and custom Lithops runtime already deployed, and ready to be used in consequent computations |


## Summary of configuration keys for Standalone

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|standalone | backend | ibm_vpc |no | Standalone compute backend implementation. IBM VPC is the default |
|standalone | runtime | python3 | no | Runtime name to run the functions. Can be a Docker image name |
|standalone | auto_dismantle | True |no | If False then the VM is not stopped automatically. Run **exec.dismantle()** explicitly to stop the VM. |
|standalone | soft_dismantle_timeout | 300 |no| Time in seconds to stop the VM instance after a job **completed** its execution |
|standalone | hard_dismantle_timeout | 3600 | no | Time in seconds to stop the VM instance after a job **started** its execution |
