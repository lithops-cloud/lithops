# Azure Container Apps

Lithops with Azure Container Apps as serverless compute backend.

## Installation

1. Install Microsoft Azure backend dependencies:

```
python3 -m pip install lithops[azure]
```

2. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

3. Install the [Azure Functions core tools](https://github.com/Azure/azure-functions-core-tools)

4. Sign in with the Azure CLI:

```bash
  az login
```

5. Create a Resource Group and a Storage Account:

   Option 1:

     1. Access to the [Azure portal Resource Groups](https://portal.azure.com/#blade/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** (or similar) in your preferred region. If you already have a resource group, omit this step.
     
     2. Access to the [Azure portal Storage Accounts](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts) and create a new Storage Account with a unique name, for example: **lithops0sa25s1**. If you already have a storage account, omit this step.

   Option 2:

    1. Create a Resource Group in a specific location. If you already have a resource group, omit this step.
    
    ```bash
      az group create --name LithopsResourceGroup --location westeurope
    ```
    
    2. Create a Storage Account with a unique name. If you already have a storage account, omit this step.
    
    ```bash
      storage_account_name=lithops$(openssl rand -hex 3)
      echo $storage_account_name
      az storage account create --name $storage_account_name --location westeurope \
         --resource-group LithopsResourceGroup --sku Standard_LRS
    ```

    3. Create a Container App environment named lithops.
    ```bash
      az extension add --name containerapp --upgrade
      az provider register --namespace Microsoft.App
      az provider register --namespace Microsoft.OperationalInsights
      az containerapp env create --name lithops --resource-group LithopsResourceGroup --location westeurope
    ```


## Configuration

6. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

7. In the left menu, under the settings section, click on *Access Keys* and copy the *Key 1*

8. Edit your lithops config and add the following keys:

```yaml
  lithops:
      backend : azure_containers

  azure_storage:
      storage_account_name: <STORAGE_ACCOUNT_NAME>
      storage_account_key: <STORAGE_ACCOUNT_KEY>

  azure_containers:
      location: <LOCATION>
      resource_group: <RESOURCE_GROUP_NAME>
```

## Summary of configuration keys for Azure

## Azure

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_storage| storage_account_name | |yes |  The name generated in the step 5 of the installation |
|azure_storage| storage_account_key |  | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Settings* > *Access Keys*|

### Azure Functions

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_containers| resource_group | |yes | Name of the resource group used in the step 5 of the installation. |
|azure_containers| location |  |yes | The location where you created the 'lithops' Container APP environment|
|azure_containers| environment | lithops |no | The environemnt name you created in the step 5 of the installation |
|azure_containers | docker_server | index.docker.io |no | Docker server URL |
|azure_containers | docker_user | |no | Docker hub username |
|azure_containers | docker_password | |no | Login to your docker hub account and generate a new access token [here](https://hub.docker.com/settings/security)|
|azure_containers | max_workers | 1000 | no | Max number of parallel workers. Although Azure limits the number of parallel workers to 30, it is convenient to keep this value high|
|azure_containers | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|azure_containers| runtime |  |no | Docker image name|
|azure_containers | runtime_memory | 512 |no | Memory limit in MB. Default 512Mi |
|azure_containers | runtime_timeout | 600 |no | Runtime timeout in seconds. Default 10 minutes |
|azure_containers| invocation_type | event  | no | Currently it supports event invocation|
|azure_containers | invoke_pool_threads | 32 |no | Number of concurrent threads used for invocation |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops test -b azure_containers -s azure_storage
```


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```
