# Lithops on Microsoft Azure

Cloudbutton toolkit with Azure Function App as compute backend.

### Installation

  1. Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)
  
  2. Sign in with the Azure CLI:
  
    ```bash
      $ az login
    ```

### Configuration

  3. Edit your lithops config and add the following keys:

    ```yaml
      lithops:
        compute_backend : azure_fa
    
      azure_fa:
        resource_group : <RESOURCE_GROUP>
        location : <CONSUMPTION_PLAN_LOCATION>
        account_name : <STORAGE_ACCOUNT_NAME>
        account_key : <STORAGE_ACCOUNT_KEY>
        functions_version : <AZURE_FUNCTIONS_VERSION>
    ```
   - `resource_group`: the Resource Group of your Storage Account. *Storage Account* > `account_name` > *Overview*.
   - `account_name`: the name of the Storage Account.
   - `account_key`: an Account Key, found in *Storage Account* > `account_name` > *Settings* > *Access Keys*.
   - `location`: the location of the consumption plan for the runtime. \
      Use `az functionapp list-consumption-locations` to view available locations.
   - `functions_version`: optional, Azure Functions runtime version (2 or 3, defaults to 2).
      

### Verify

4. Test if Cloudbutton on Azure is working properly:

   Run the next command:
   
   ```bash
   $ cloudbutton test
   ```
   
   or run the next Python code:
   
   ```python
   from cloudbutton.engine.executor import FunctionExecutor
   
   def hello_world(name):
       return 'Hello {}!'.format(name)
    
   if __name__ == '__main__':
        cb_exec = FunctionExecutor()
        cb_exec.call_async(hello_world, 'World')
        print("Response from function: ", cb_exec.get_result())
   ```

  
*Note: the first time executing it it will take several minutes to deploy the runtime. If you want to see more information about the process, you can enable logging by passing the argument `FunctionExecutor(log_level='INFO')`. If you are having troubles when executing it for the first time, try updating your ```pip```.*
