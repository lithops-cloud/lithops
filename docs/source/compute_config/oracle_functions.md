# Oracle Functions

Lithops with *Oracle Functions* as serverless compute backend.

**Note**: This is a beta backend. Please open an issue if you encounter any error/bug

## Installation

1. Install Oracle Cloud backend dependencies:

```bash
python3 -m pip install lithops[oracle]
```

2. Access to your [Oracle Cloud Console](https://cloud.oracle.com/) and activate your Functions service instance.

## Configuration


### Creating a Dynamic Group

1. **Sign in to the Oracle Cloud Console.** 

2. **Open the navigation menu.** Under Identity & Security , go to Polices and then click **Domains**.

3. On the left menu, select one compartment. Your account name is the dfault compartment.

4. Click on the current Domain (It's called **Default** by default) and then click on **Dynamic groups**. Click **Create Dynamic Group.**

5. In the **Create Dynamic Group** dialog box:

    - Give your dynamic group a **Name** (for example: lithops) and **Description**.
  
    - In the **Matching Rule** box, paste the next rule, where <compartment_id> is the OCID of the compartment where the application and associated functions will be deployed. You can obtain it from [here](https://cloud.oracle.com/identity/compartments):

        ```
        ALL {resource.type = 'fnfunc', resource.compartment.id = '<compartment_id>'}
        ```
    
6. **Click Create** to create the dynamic group.


### Creating a Policy for the Dynamic Group

Now that the dynamic group is set up, you'll need to create a policy that allows this group to manage resources.

1. **Open the navigation menu again.** Under Governance and Administration, go to Identity, and then click [**Policies**](https://cloud.oracle.com/identity/domains/policies).

2. Choose your **compartment** and Click on the **Create Policy** button.

3. **In the Create Policy dialog box:**

    - Give your policy a **Name** (for example: lithops) and **Description**.
    
    - In the **Statement** box, input the policy statement that grants permissions. Replace `<group_name>` with the name of the dynamic group you just created:

        ```
        Allow dynamic-group <group_name> to manage all-resources in tenancy
        ```

5. **Click Create** to create the policy.


### Configure lithops
Now, your Oracle Functions have the necessary permissions to manage resources in your Oracle Cloud Infrastructure tenancy.

1. Navigate to the [VCNs page](https://cloud.oracle.com/networking/vcns) and create a new VCN using the **VCN Wizard**. Then choose *create VCN with Internet Connectivity*. In the next page, you can uncheck `Use DNS hostnames in this VCN` and leave the rest of the parameters as provided by default.

2. The **VCN Wizard** will create all the necessary VCN resources, including the subnets. Now access the private subnet and copy the OCID to the `subnet_id` parameter under the `oracle_f` section of the configuration.

3. Navigate to the [API keys page](https://cloud.oracle.com/identity/domains/my-profile/api-keys) and generate and download a new API signing keys. Omit this step if you already generated and downloaded one key. When you generate a new Key, oracle provides a sample config file with most of the required parameters by lithops. Copy all the `key:value` pairs and configure lithops as follows:


```yaml
lithops:
    backend: oracle_f

oracle:
    user: <USER>
    region: <REGION>
    fingerprint: <FINGERPRINT>
    tenancy: <TENANCY>
    key_file: <KEY_FILE>
    compartment_id: <COMPARTMENT_ID>

oracle_f:
    subnet_id: <SUBNET_OCID>
```


Also, remember to login into your Oracle container registry before you build your runtime. This is because runtimes are uploaded to the Oracle container registry. `<username>` is probably your email address. You can create a new auth token [here](https://cloud.oracle.com/identity/domains/my-profile/auth-tokens)

```
docker login <region>.ocir.io -u <tenancy-namespace>/<username> -p <authentication_token>
```

## Summary of configuration keys for Oracle:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle | user | |yes |  Oracle Cloud User's OCID from [here](https://cloud.oracle.com/identity/domains/my-profile) |
|oracle | region | |yes | Region Identifier from [here](https://cloud.oracle.com/regions). For example: `eu-madrid-1` |
|oracle | fingerprint | |yes | Fingerprint of the private key PEM file from [here](https://cloud.oracle.com/identity/domains/my-profile/api-keys)|
|oracle | tenancy | |yes | Tenancy's OCID from [here](https://cloud.oracle.com/tenancy)|
|oracle | key_file | |yes | Path to the private key (PEM) file |
|oracle | compartment_id | |yes | Compartment's ID from [here](https://cloud.oracle.com/identity/compartments)|
|oracle | tenancy_namespace | |no | Auto-generated Object Storage namespace string of the tenancy. You can find it [here](https://cloud.oracle.com/tenancy), under *Object storage namespace*|


## Summary of configuration keys for Oracle Functions :

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_f | subnet_id |  |yes | Private subnet OCID |
|oracle_f | region | |no | Region name. For example: `eu-madrid-1`. Lithops will use the region set under the `oracle` section if it is not set here |
|oracle_f | max_workers | 300 | no | Max number of workers. Oracle limits to 60 GB RAM, any number of workers  |
|oracle_f | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|oracle_f | runtime |  |no | Runtime name you built and deployed using the lithops client|
|oracle_f | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|oracle_f | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|oracle_f | runtime_include_function | False | no | If set to true, Lithops will automatically build a new runtime, including the function's code, instead of transferring it through the storage backend at invocation time. This is useful when the function's code size is large (in the order of 10s of MB) and the code does not change frequently |


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b oracle_f -s oracle_oss
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```