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


## Deploy PyWren main runtime

You need to deploy the PyWren runtime to your IBM Cloud Functions namespace and create the main PyWren action. PyWren main action is responsible to execute Python functions inside PyWren runtime within IBM Cloud Functions. The strong requirement here is to match Python versions between the client and the runtime. The runtime may also contain additional packages which your code depends on.

PyWren-IBM-Cloud shipped with default runtime:

| Runtime name | Python version | Packages included |
| ----| ----| ---- |
| pywren_3.6 | 3.6 | [list of packages](https://github.com/ibm-functions/runtime-python/blob/master/python3.6/CHANGELOG.md) |

To deploy the default runtime, navigate into `runtime` folder and execute:

	./deploy_runtime

This script will automatically create a Python 3.6 action named `pywren_3.6` which is based on `python:3.6` IBM docker image (Debian Jessie). 
This action is the main runtime used to run functions within IBM Cloud Functions with PyWren. 

If your client uses different Python version or there is need to add additional packages to the runtime, then it is necessary to build a custom runtime. Detail instructions can be found [here](../runtime/).
