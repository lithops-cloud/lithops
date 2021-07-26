# Lithops on Microsoft Azure Batch (under development)

Lithops with Azure Batch as serverless compute backend.

### Installation

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

     1. Access to the [Azure portal Resource Groups](https://portal.azure.com/#blade/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** in your preferred region. If you already have a resource group, omit this step.
     
     2. Access to the [Azure portal Storage Accounts](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts) and create a new Storage Account with a unique name, for example: **lithops0sa25s1** If you already have a storage account, omit this step.

   Option 2:

    1. Create a Resource Group in a specific location. If you already have a resource group, omit this step.
    
    ```bash
      $ az group create --name LithopsResourceGroup --location westeurope
    ```
    
    2. Create a Storage Account with a unique name. If you already have a storage account, omit this step.
    
    ```bash
      $ storage_account_name=lithops$(openssl rand -hex 3)
      $ echo $storage_account_name
      $ az storage account create --name $storage_account_name --location westeurope \
         --resource-group LithopsResourceGroup --sku Standard_LRS
    ```


### Configuration

6. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

7. In the left menu, under the settings section, click on *Access Keys* and copy the *Key 1*

8. Access to the [Batch account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Batch%2FbatchAccounts)

9. In the left menu, under the setting section, click on *Keys* and copy the *Primary Key* and the *URL*

10. Edit your lithops config and add the following keys:

```yaml
  lithops:
      backend : azure_batch

  azure_storage:
      storage_account_name: <STORAGE_ACCOUNT_NAME>
      storage_account_key: <STORAGE_ACCOUNT_KEY>

  azure_batch:
      batch_account_name: <BATCH_ACCOUNT_NAME>
      batch_account_key: <BATCH_ACCOUNT_KEY>
      batch_account_url: <BATCH_ACCOUNT_URL>
```

### Summary of configuration keys for Azure:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_storage| storage_account_name | |yes |  The storage account name |
|azure_storage| storage_account_key |  | yes |  An Account Key, found in *Batch Accounts* > `account_name` > *Settings* > *Access Keys*|

### Summary of configuration keys for Azure batch:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_batch| batch_account_name | |yes | The batch account name |
|azure_batch| batch_account_key | |yes |  The account key, found in *batch Accounts* > `account_name` > *Settings* > *Keys*|
|azure_batch| batch_account_url |  |yes | The account, found in *batch Accounts* > `account_name` > *Settings* > *Keys*|
|azure_batch| poolvmsize |  |no | [VM size](https://docs.microsoft.com/es-es/azure/cloud-services/cloud-services-sizes-specs).|
