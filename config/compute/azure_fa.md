# Lithops on Microsoft Azure

Lithops with Azure Function App as serverless compute backend.

### Installation

1. Install Microsoft Azure backend dependencies:

```
$ pip install lithops[azure]
```

2. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)

3. Install the [Azure Functions core tools](https://github.com/Azure/azure-functions-core-tools)

4. Sign in with the Azure CLI:

```bash
  $ az login
```

5. Create a Resource Group in a specific location, for example:

```bash
  $ az group create --name LithopsResourceGroup --location westeurope
```

6. Create a Storage Account with a unique name, for example:

```bash
  $ storage_account_name=lithops$(openssl rand -hex 3)
  $ echo $storage_account_name
  $ az storage account create --name $storage_account_name --location westeurope \
     --resource-group LithopsResourceGroup --sku Standard_LRS
```


### Configuration

7. Access to the [Azure portal](https://portal.azure.com/#home)

8. Access to the [Storage Account](https://portal.azure.com/#blade/HubsExtension/BrowseResource/resourceType/Microsoft.Storage%2FStorageAccounts)

9. In the left menu, click on *Access Keys* and copy the *Key 1* key

10. Edit your lithops config and add the following keys:

```yaml
  serverless:
    backend : azure_fa

  azure_fa:
    resource_group: <RESOURCE_GROUP>
    storage_account: <STORAGE_ACCOUNT_NAME>
    storage_account_key: <STORAGE_ACCOUNT_KEY>
    location: <CONSUMPTION_PLAN_LOCATION>
```

### Summary of configuration keys for Azure Functions Apps:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|azure_fa| resource_group | |yes | Name of the resource group used in the step 5 of the installation. |
|azure_fa| storage_account | |yes |  The name generated in the step 6 of the installation |
|azure_fa| storage_account_key |  | yes |  An Account Key, found in *Storage Accounts* > `account_name` > *Settings* > *Access Keys*|
|azure_fa| location |  |yes | The location of the consumption plan for the runtime. Use `az functionapp list-consumption-locations` to view the available locations.|
