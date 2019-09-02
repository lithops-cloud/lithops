# Installation for Developers

Clone the repository and run the setup script:

    git clone https://github.com/pywren/pywren-ibm-cloud
    or
    git clone git@github.com:pywren/pywren-ibm-cloud.git

Navigate into `pywren-ibm-cloud` folder

    cd pywren-ibm-cloud/

If you plan to develop code, stay in the master branch. Otherwise obtain the most recent stable release version from the `release` tab. For example, if release is `v1.0.19` then execute

	git checkout v1.0.19

Build and install 
	
    python3 setup.py develop

## Configuration

Once installed, follow [configuration](../config/) instructions to make PyWren running.


## Runtime
The default runtime is automatically deployed the first time you execute an IBM-PyWren job (for more information about runtimes navigate to [runtime/](../runtime/) folder). Then, every time you want to test your changes, you need to update the already deployed runtime(s). To do so, you have multiple options.

To update the default runtime, navigate into `runtime` folder and execute:

	./pywren_runtime update default

To update any other runtime, navigate into `runtime` folder and execute:

	./pywren_runtime update <docker_username/runtimename:tag>


To update all deployed runtimes at a time, navigate into `runtime` folder and execute:

	./pywren_runtime update all
