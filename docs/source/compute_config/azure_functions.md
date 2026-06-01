# Azure Functions

Lithops with Azure Functions as serverless compute backend.

## Installation

1. Install Microsoft Azure backend dependencies:

```bash
python3 -m pip install lithops[azure]
```

2. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

3. Sign in with the Azure CLI:

```bash
az login
```

4. Create a Resource Group and a Storage Account:

   Option 1:

     1. Access the [Azure portal Resource Groups](https://portal.azure.com/#view/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** (or similar) in your preferred region. If you already have a resource group, omit this step.
     
     2. Access the [Azure portal Storage Accounts](https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts) and create a new Storage Account with a unique name, for example: **lithops0sa25s1**. If you already have a storage account, omit this step.

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

1. Access the [Storage Account](https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

2. In the left menu, under the *Security + networking* section, click on *Access Keys* and copy the *Key 1*

3. Edit your Lithops config and add the following keys:

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

### Azure Storage

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_storage| storage_account_name | |yes |  Storage account name. The name generated in step 4 of the installation if you followed these instructions |
|azure_storage| storage_account_key |  | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Security + networking* > *Access Keys*|

### Azure Functions

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_functions| resource_group | |no | Name of a resource group, for example: `LithopsResourceGroup`. Lithops will use the `resource_group` set under the `azure` section if it is not set here |
|azure_functions| region |  |no | The Flex Consumption plan location for the runtime. Use `az functionapp list-flexconsumption-locations` to view the available locations. For example: `westeurope`, `westus2`, etc. Lithops will use the `region` set under the `azure` section if it is not set here|
|azure_functions | runtime_memory | 2048 | no | Flex Consumption instance memory in MB. Supported values: `512`, `2048`, `4096`. Other values are mapped to the nearest supported size |
|azure_functions | max_workers | 1000 | no | Max number of parallel workers. Although Azure limits the number of workers to 200, it is convenient to keep this value high|
|azure_functions | worker_processes | 1 | no | Lithops-side parallelism setting. Not applied as an Azure Functions app setting on Flex Consumption |
|azure_functions| runtime |  |no | Runtime name already deployed in the service|
|azure_functions | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|azure_functions| trigger | pub/sub  | no | One of 'https' or 'pub/sub'|
|azure_functions | invoke_pool_threads | 100 |no | Number of concurrent threads used for invocation |


## Test Lithops
Once you have your compute and storage backends configured, you can run a Hello World function with:

```bash
lithops hello -b azure_functions -s azure_storage
```


## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```