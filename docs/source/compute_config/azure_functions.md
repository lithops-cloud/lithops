# Azure Functions

Lithops with Azure Functions as serverless compute backend.

*Note that currently Azure functions supports Python 3.6, 3.7, 3.8 and 3.9. So you must use one of these versions in your client machine.*

## Installation

1. Install Microsoft Azure backend dependencies:

```
$ python3 -m pip install lithops[azure]
```

2. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

3. Install the [Azure Functions core tools](https://github.com/Azure/azure-functions-core-tools)

4. Sign in with the Azure CLI:

```bash
  $ az login
```

5. Create a Resource Group and a Storage Account:

   Option 1:

     1. Access to the [Azure portal Resource Groups](https://portal.azure.com/#blade/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** (or similar) in your preferred region. If you already have a resource group, omit this step.
     
     2. Access to the [Azure portal Storage Accounts](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts) and create a new Storage Account with a unique name, for example: **lithops0sa25s1**. If you already have a storage account, omit this step.

   Option 2:

    1. Create a Resource Group in a specific location. If you already have a resource group, omit this step.
    
    ```bash
      $ az group create --name LithopsResourceGroup --location westeurope
    ```
    
    2. Create a Storage Account with a unique name. If you already have a storage account, omit this step.
    
    ```bash
      $ storage_account_name=lithops$(openssl rand -hex 3)
      $ echo $storage_account_name
      $ az storage_config account create --name $storage_account_name --location westeurope \
         --resource-group LithopsResourceGroup --sku Standard_LRS
    ```


## Configuration

6. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

7. In the left menu, under the settings section, click on *Access Keys* and copy the *Key 1*

8. Edit your lithops config and add the following keys:

```yaml
  lithops:
      backend : azure_functions

  azure_storage:
      storage_account_name: <STORAGE_ACCOUNT_NAME>
      storage_account_key: <STORAGE_ACCOUNT_KEY>

  azure_functions:
      location: <CONSUMPTION_PLAN_LOCATION>
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
|azure_functions| resource_group | |yes | Name of the resource group used in the step 5 of the installation. |
|azure_functions| location |  |yes | The location of the consumption plan for the runtime. Use `az functionapp list-consumption-locations` to view the available locations.|
|azure_functions | max_workers | 200 | no | Max number of workers per `FunctionExecutor()`|
|azure_functions | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|azure_functions| runtime |  |no | Runtime name already deployed in the service|
|azure_functions | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|azure_functions| invocation_type | http  | no | One of 'http' or 'event'|
|azure_functions | invoke_pool_threads | 100 |no | Number of concurrent threads used for invocation |
