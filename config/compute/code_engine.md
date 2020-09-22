# Lithops on IBM Code Engine

**Notice that IBM Code Engine is still in beta. Use this only for testing**

IBM Code Engine is based on Knative, so the only requirement to make it working is to have the KUBECONFIG file properly configured. To do so, follow the next steps:

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
   ibmcloud plugin install code-engine
   ```

4. Create a new Coligo project (you can also do this through the dashboard):

   ```bash
   ibmcloud ce project create --name myproject
   ```

5. Target to this project:

   ```bash
   ibmcloud ce project select --name myproject
   
6. Locate the kubernetes config file:

   ```bash
   ibmcloud ce project current
   ```
7. Set the KUBECONFIG environment variable:

   ```bash
   export KUBECONFIG=/home/myuser/.bluemix/plugins/code-engine/prova-349f13c4-e106-462c-90ae-51cfe70b591e.yaml
   ```

8. [Install the Docker CE version](https://docs.docker.com/get-docker/) (Lithops needs to built the default runtime the first time you run a script)

9. Login to your docker account:
   ```bash
   docker login
   ```

### Configuration

6. Edit your lithops config file and add the following keys:

   ```yaml
   lithops:
       compute_backend: knative

   knative:
       docker_user: username
       docker_token: 12e9075f-6cd7-4147-a01e-8e34ffe9196e
       cpu: 1000  # CPU limit in millicpu
   ```
   - **docker_token**: Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)


### Verify

7. Test if Lithops on Coligo is working properly:

   Run the next command:

   ```bash
   $ lithops test
   ```

   or run the next Python code:

   ```python
   import lithops

   def hello_world(name):
       return 'Hello {}!'.format(name)

   if __name__ == '__main__':
       kn = lithops.knative_executor()
       kn.call_async(hello_world, 'World')
       print("Response from function: ", kn.get_result())
   ```
