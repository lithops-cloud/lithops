# Lithops on Microsoft Azure Blob Storage

Lithops with Azure Blob Storage as storage backend.


### Installation

1. Install Microsoft Azure backend dependencies:

```
$ python3 -m pip install lithops[azure]
```

2. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

3. Sign in with the Azure CLI:

```bash
  $ az login
```

4. Create a Resource Group in a specific location, for example:

```bash
  $ az group create --name LithopsResourceGroup --location westeurope
```

5. Create a Storage Account with a unique name, for example:

```bash
  $ storage_account_name=lithops$(openssl rand -hex 3)
  $ echo $storage_account_name
  $ az storage account create --name $storage_account_name --location westeurope \
     --resource-group LithopsResourceGroup --sku Standard_LRS
```

6. Alternatively, you can create the Resource group and the Storage Account through the [dashboard](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts).


### Configuration

1. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

2. In the left menu, click on *Access Keys* and copy the *Key 1* key

3. In the left menu, navigate to Blob service --> Containers, and create a new container (e.g. `lithops-data`). Remember to update the `storage_bucket` Lithops config field with this container name.

1. Edit your lithops config and add the following keys:

```yaml
  lithops:
      storage : azure_blob
      storage_bucket: <CONTAINER_NAME>

  azure_blob:
      storage_account : <STORAGE_ACCOUNT_NAME>
      storage_account_key : <STORAGE_ACCOUNT_KEY>
```

### Summary of configuration keys for Azure Functions Apps:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_blob| storage_account | |yes |  The name generated in the step 5 of the installation |
|azure_blob| storage_account_key |  | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Settings* > *Access Keys*|
