# Lithops with DSO

Lithops with [DSO](https://github.com/crucial-project/dso/tree/2.0) as storage backend.

*Notice:* Only works with IBM Cloud Functions.

### Usage

1. Deploy a custom runtime as follows:

		lithops runtime build -f runtime/ibm_cf/Docker.dso id/runtime:tag
		lithops runtime create id/runtime:tag

1. Create a DSO server in the Cloud following the instructions available [here](https://github.com/crucial-project/dso/tree/2.0)

2. Run a script using a command of the form `"DSO=IP:11222" python3 my_script.py`, where `DSO` is the address of a running DSO deployment.

