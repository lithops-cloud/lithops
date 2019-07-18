# Installation for Developers

Clone the repository and run the setup script:

    git clone https://github.com/pywren/pywren-ibm-cloud
    or
    git clone git@github.com:pywren/pywren-ibm-cloud.git

Navigate into `pywren-ibm-cloud` folder

    cd pywren-ibm-cloud/

If you plan to develop code, stay in the master branch. Otherwise obtain the most recent stable release version from the `release` tab. For example, if release is `v1.0.5` then execute

	git checkout v1.0.5

Build and install 
	
    python3 setup.py develop

## Configuration

Configure PyWren client with access details to your IBM Cloud Object Storage (COS) account, and with your IBM Cloud Functions account.

Access details to IBM Cloud Functions can be obtained [here](https://cloud.ibm.com/openwhisk/learn/api-key). Details on your IBM Cloud Object Storage account can be obtained from the "service credentials" page on the UI of your COS account. More details on "service credentials" can be obtained [here](docs/cos-info.md).

There are two options to configure PyWren:

### Using configuration file
Copy the `ibmcf/default_config.yaml.template` into `~/.pywren_config`

Edit `~/.pywren_config` and configure the following entries:

```yaml
pywren: 
    storage_bucket: <BUCKET_NAME>

ibm_cf:
    # Region endpoint example: https://us-east.functions.cloud.ibm.com
    endpoint    : <REGION_ENDPOINT>  # make sure to use https:// as prefix
    namespace   : <NAMESPACE>
    api_key     : <API_KEY>
   
ibm_cos:
    # Region endpoint example: https://s3.us-east.cloud-object-storage.appdomain.cloud
    endpoint   : <REGION_ENDPOINT>  # make sure to use https:// as prefix
    # this is preferable authentication method for IBM COS
    api_key    : <API_KEY>
    # alternatively you may use HMAC authentication method
    # access_key : <ACCESS_KEY>
    # secret_key : <SECRET_KEY>

```

You can choose different name for the config file or keep it into different folder. If this is the case make sure you configure system variable 
	
	PYWREN_CONFIG_FILE=<LOCATION OF THE CONFIG FILE>


### Configuration in the runtime
This option allows you pass all the configuration details as part of the PyWren invocation in runtime. All you need is to configure a Python dictionary with keys and values, for example:

```python
config = {'pywren' : {'storage_bucket' : 'BUCKET_NAME'},

          'ibm_cf':  {'endpoint': 'HOST', 
                      'namespace': 'NAMESPACE', 
                      'api_key': 'API_KEY'}, 

          'ibm_cos': {'endpoint': 'REGION_ENDPOINT', 
                      'api_key': 'API_KEY'}}
```


You can find more configuration keys [here](configuration.md).


## Runtime

Every time you want to test the changed code, you need to update the default PyWren runtime to your IBM Cloud Functions namespace. PyWren main runtime is responsible to execute Python functions within IBM Cloud Functions cluster. The strong requirement here is to match Python versions between the client and the runtime. The runtime may also contain additional packages which your code depends on.

PyWren-IBM-Cloud shipped with default runtimes:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| ibmfunctions/pywren:3.5 | 3.5 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.6/CHANGELOG.md) |
| ibmfunctions/action-python-v3.6 | 3.6 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.6/CHANGELOG.md) |
| ibmfunctions/action-python-v3.7 | 3.7 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.7/CHANGELOG.md) |

To update the default runtime, navigate into `runtime` folder and execute:

	./pywren_runtime update default

To update any other runtime, navigate into `runtime` folder and execute:

	./pywren_runtime update <docker_username/runtimename:tag>


If your client uses different Python version or there is need to add additional packages to the runtime, then it is necessary to build a custom runtime. Detail instructions can be found [here](../runtime/).
