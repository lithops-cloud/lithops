# PyWren on IBM Coligo (Experimental)

**Notice that IBM Coligo is still in beta. Use this only for testing**

IBM Coligo is based on Knative, so the only requirement to make it working is to have the KUBECONFIG file properly configured. To do so, follow the next steps:

### Installation

1. Install the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli):

   ```bash
   curl -sL https://ibm.biz/idt-installer | bash
   ```

2. Login to your account (IBM Coligo is currently present on us_south region, so login to this region)

   ```bash
   ibmcloud login -r us_south
   ```

3. Install the IBM Coligo plugin:

   ```bash
   ibmcloud plugin install coligo
   ```

4. Create a new Coligo project (you can also do this through the dashboard):

   ```bash
   ibmcloud coligo project create --name myproject
   ```

5. Target to this project:

   ```bash
   ibmcloud coligo target --name myproject
   ```
   After running the target command, you will see in your screen the location of the KUBECONFIG file of your Coligo project. Set the KUBECONFIG environment variable, for example:

   ```bash
   export KUBECONFIG=/home/myuser/.bluemix/plugins/coligo/myproject-b59a1c9f-5ds6-j1sm5.yaml
   ```

7. [Install the Docker CE version](https://docs.docker.com/get-docker/) (PyWren needs to built the default runtime the first time you run a script)

8. Login to your docker account:
   ```bash
   docker login
   ```

### Configuration

6. Edit your pywren config file and add the following keys:

   ```yaml
   pywren:
       compute_backend: knative

   knative:
       docker_user: username
       docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
       cpu: 1000  # CPU limit in millicpu
   ```
   - **docker_token**: Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)


#### Summary of configuration keys for Knative:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|knative | istio_endpoint | |no | Istio IngressGateway Endpoint. Make sure to use http:// prefix |
|knative | docker_user | |yes | Docker hub username |
|knative | docker_token | |yes | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|knative | git_url | |no | Git repository to build the image |
|knative | git_rev | |no | Git revision to build the image |
|knative | cpu | 1000 |no | CPU limit in millicpu. Default 1vCPU (1000m) |


### Verify

7. Test if PyWren on Coligo is working properly:

   Run the next command:

   ```bash
   $ pywren-ibm-cloud test
   ```

   or run the next Python code:

   ```python
   import pywren_ibm_cloud as pywren

   def hello_world(name):
       return 'Hello {}!'.format(name)

   if __name__ == '__main__':
       kn = pywren.knative_executor()
       kn.call_async(hello_world, 'World')
       print("Response from function: ", kn.get_result())
   ```
