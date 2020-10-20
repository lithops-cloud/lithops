# Lithops configuration

You can either configure Lithops with configuration file or provide configuration keys in runtime

## Create a configuration file

To configure Lithops through a [configuration template file](config_template.yaml) you have multiple options:

1. Create e new file called `config` in the `~/.lithops` folder.

2. Create a new file called `.lithops_config` in the root directory of your project from where you will execute your Lithops scripts.

3. Create the config file in any other location and configure the `LITHOPS_CONFIG_FILE` system environment variable:


	 	LITHOPS_CONFIG_FILE=<CONFIG_FILE_LOCATION>
    
## Configuration keys in runtime

An alternative mode of configuration is to use a python dictionary. This option allows to pass all the configuration details as part of the Lithops invocation in runtime, for example:

```python
import lithops

config = {'lithops' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'HOST',
                      'namespace': 'NAMESPACE',
                      'api_key': 'API_KEY'},

          'ibm_cos': {'endpoint': 'ENDPOINT',
                      'private_endpoint': 'PRIVATE_ENDPOINT',
                      'api_key': 'API_KEY'}}
```
