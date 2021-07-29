# Development

This doc explains how to set up a development environment so you can get started contributing to Lithops

Clone the repository and run the setup script:

    git clone https://github.com/lithops-cloud/lithops
    or
    git clone git@github.com:lithops-cloud/lithops.git

Navigate into `lithops` folder

    cd lithops/

If you plan to develop code, stay in the master branch. Otherwise obtain the most recent stable release version from the `release` tab. For example, if release is `v2.2.5` then execute

	git checkout v2.2.5

Build and install 
	
    python3 setup.py develop

## Configuration

Once installed, follow [configuration](config/) instructions to make Lithops running.


## Runtime
The default runtime is automatically deployed the first time you execute an Lithops job (for more information about runtimes navigate to [runtime/](runtime/) folder). Then, every time you want to test your changes, you need to update the already deployed runtime(s). To do so, you have multiple options.

To update the default runtime, navigate into `runtime` folder and execute:

	# lithops runtime update default

To update any other runtime, navigate into `runtime` folder and execute:

	# lithops runtime update <docker_username/runtimename:tag>


To update all deployed runtimes at a time, navigate into `runtime` folder and execute:

	# lithops runtime update all


## Contributing

Follow [contributing](CONTRIBUTING.md) instructions if you want to publish your changes to the Lithops master branch.
