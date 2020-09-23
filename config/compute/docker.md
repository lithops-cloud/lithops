# Lithops on Docker

Lithops with *Docker* as compute backend. Lithops can run functions inside a dokcer container either in the localhost or in a remote host. Currently, IBM Cloud Functions and Knative containers are compatible with this mode of execution.


### Installation

1. [Install the Docker CE version](https://docs.docker.com/get-docker/) in your localhost and in the remote host if you plan to run functions remotely.


### Configuration

#### Option 1 (Localhost):

2. Edit your lithops config file and add the following keys:

   ```yaml
   lithops:
       compute_backend: docker

   docker:
       host: 127.0.0.1
   ```


#### Option 2 (Remote host):

2. Edit your lithops config file and add the following keys:

   ```yaml
   lithops:
       compute_backend: docker

   docker:
       host: <IP_ADDRESS>
       ssh_user: <SSH_USERNAME>
       ssh_password: <SSH_PASSWORD>
       ssh_key_filename: <SSH_KEY_PATH>
   ```

#### Summary of configuration keys for docker:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|docker | host | localhost |no | IP Address of the host/VM to run the functions |
|docker | ssh_user | |no | SSH username (mandatory for remote host)|
|docker | ssh_password | |no | SSH password (mandatory for remote host and no key file)|
|docker | ssh_key_filename | |no | Private SSH key filename. Will use the default path if not provided|
