# Azure Blob Storage

Lithops with Azure Blob Storage as storage backend.


## Installation

1. Install Microsoft Azure backend dependencies:

```bash
$ python3 -m pip install lithops[azure]
```

2. Create a Resource Group and a Storage Account:

   Option 1:

     1. Access to the [Azure portal Resource Groups](https://portal.azure.com/#blade/HubsExtension/BrowseResourceGroups) and create a new Resource group named **LithopsResourceGroup** in your preferred region. If you already have a resource group, omit this step.
     
     2. Access to the [Azure portal Storage Accounts](https://portal.azure.com/#blade/HubsExtension/BrowseResourceGroups) and create a new Storage Account with a unique name, for example: **lithops0sa25s1**. If you already have a storage account, omit this step.

   Option 2:
   
    1. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

    2. Sign in with the Azure CLI:

    ```bash
      $ az login
    ```

    3. Create a Resource Group in your preferred region. If you already have a resource group, omit this step.
    
    ```bash
      $ az group create --name LithopsResourceGroup --location westeurope
    ```
    
    4. Create a Storage Account with a unique name. If you already have a storage account, omit this step.
    
    ```bash
      $ storage_account_name=lithops$(openssl rand -hex 3)
      $ echo $storage_account_name
      $ az storage account create --name $storage_account_name --location westeurope \
         --resource-group LithopsResourceGroup --sku Standard_LRS
    ```

## Configuration

1. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

2. In the left menu, under the *Security + networking* section, click on *Access Keys* and copy the *Key 1*

3. Edit your lithops config and add the following keys:

```yaml
  lithops:
      storage : azure_storage

  azure_storage:
      storage_account_name: <STORAGE_ACCOUNT_NAME>
      storage_account_key: <STORAGE_ACCOUNT_KEY>
```

## Summary of configuration keys for Azure Storage:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_storage | storage_account_name | | yes |  The storage account name |
|azure_storage | storage_account_key  | | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Security + networking* > *Access Keys*|
|azure_storage | storage_bucket | | no | The name of a container that exists in you account. This will be used by Lithops for intermediate data. Lithops will automatically create a new one if it is not provided |
