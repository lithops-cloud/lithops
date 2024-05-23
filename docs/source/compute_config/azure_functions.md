# Azure Functions

Lithops with Azure Functions as serverless compute backend.

## Installation

1. Install Microsoft Azure backend dependencies:

```bash
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

     1. Access to the [Azure portal Resource Groups](https://portal.azure.com/#view/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** (or similar) in your preferred region. If you already have a resource group, omit this step.
     
     2. Access to the [Azure portal Storage Accounts](https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts) and create a new Storage Account with a unique name, for example: **lithops0sa25s1**. If you already have a storage account, omit this step.

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

## Configuration

1. Access to the [Storage Account](https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

2. In the left menu, under the *Security + networking* section, click on *Access Keys* and copy the *Key 1*

3. Edit your lithops config and add the following keys:

```yaml
  lithops:
      backend : azure_functions

  azure:
      resource_group: <RESOURCE_GROUP_NAME>
      region: <LOCATION>

  azure_storage:
      storage_account_name: <STORAGE_ACCOUNT_NAME>
      storage_account_key: <STORAGE_ACCOUNT_KEY>
```

## Summary of configuration keys for Azure

### Azure

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure| resource_group | | yes | Name of a resource group, for example: `LithopsResourceGroup` |
|azure| region |  |yes | Location of the resource group, for example: `westeurope`, `westus2`, etc|
|azure| subscription_id |  |no | Subscription ID from your account. Find it [here](https://portal.azure.com/#view/Microsoft_Azure_Billing/SubscriptionsBlade)|

## Azure Storage

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_storage| storage_account_name | |yes |  Storage account name. The name generated in the step 5 of the installation if you followed these instructions |
|azure_storage| storage_account_key |  | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Security + networking* > *Access Keys*|

### Azure Functions

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_functions| resource_group | |no | Name of a resource group, for example: `LithopsResourceGroup`. Lithops will use the `resource_group` set under the `azure` section if it is not set here |
|azure_functions| region |  |no | The location of the consumption plan for the runtime. Use `az functionapp list-consumption-locations` to view the available locations. For example: `westeurope`, `westus2`, etc. Lithops will use the `region` set under the `azure` section if it is not set here|
|azure_functions | max_workers | 1000 | no | Max number of parallel workers. Although Azure limits the number of workers to 200, it is convenient to keep this value high|
|azure_functions | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|azure_functions| runtime |  |no | Runtime name already deployed in the service|
|azure_functions | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|azure_functions| trigger | pub/sub  | no | One of 'https' or 'pub/sub'|
|azure_functions | invoke_pool_threads | 100 |no | Number of concurrent threads used for invocation |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b azure_functions -s azure_storage
```


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```