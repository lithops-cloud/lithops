# Oracle Functions

Lithops with *Oracle Functions* as serverless compute backend.

**Note**: This is a beta backend. Please open an issue if you encounter any errors or bugs.

## Installation

1. Install Oracle Cloud backend dependencies:

```bash
python3 -m pip install lithops[oracle]
```

2. Access your [Oracle Cloud Console](https://cloud.oracle.com/) and activate your Functions service instance.

## Configuration


### Creating a Dynamic Group

1. **Sign in to the Oracle Cloud Console.** 

2. **Open the navigation menu.** Under Identity & Security, go to Policies and then click **Domains**.

3. On the left menu, select a compartment. Your account name is the default compartment.

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

2. Choose your **compartment** and click on the **Create Policy** button.

3. **In the Create Policy dialog box:**

    - Give your policy a **Name** (for example: lithops) and **Description**.
    
    - In the **Statement** box, input the policy statement that grants permissions. Replace `<group_name>` with the name of the dynamic group you just created:

        ```
        Allow dynamic-group <group_name> to manage all-resources in tenancy
        ```

4. **Click Create** to create the policy.


### Configure Lithops

Your Oracle Functions application now has the necessary permissions to manage resources in your Oracle Cloud Infrastructure tenancy.

1. Navigate to the [VCNs page](https://cloud.oracle.com/networking/vcns) and create a new VCN using the **VCN Wizard**. Choose **Create VCN with Internet Connectivity**. On the next page, you can uncheck `Use DNS hostnames in this VCN` and leave the rest of the parameters at their defaults.

2. The **VCN Wizard** creates all the necessary VCN resources, including the subnets. Open the private subnet and copy its OCID to the `subnet_id` parameter under the `oracle_f` section of the configuration.

3. Navigate to the [API keys page](https://cloud.oracle.com/identity/domains/my-profile/api-keys) and generate and download a new API signing key. Omit this step if you have already generated and downloaded a key. When you generate a new key, Oracle provides a sample config file with most of the parameters required by Lithops. Copy all the `key:value` pairs and configure Lithops as follows:


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
    docker_password: <AUTH_TOKEN>
```

## Summary of configuration keys for Oracle

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle | user | |yes |  Oracle Cloud User's OCID from [here](https://cloud.oracle.com/identity/domains/my-profile) |
|oracle | region | |yes | Region Identifier from [here](https://cloud.oracle.com/regions). For example: `eu-madrid-1` |
|oracle | fingerprint | |yes | Fingerprint of the private key PEM file from [here](https://cloud.oracle.com/identity/domains/my-profile/api-keys)|
|oracle | tenancy | |yes | Tenancy's OCID from [here](https://cloud.oracle.com/tenancy)|
|oracle | key_file | |yes | Path to the private key (PEM) file |
|oracle | compartment_id | |yes | Compartment's ID from [here](https://cloud.oracle.com/identity/compartments)|
|oracle | tenancy_namespace | |no | Auto-generated Object Storage namespace string of the tenancy. You can find it [here](https://cloud.oracle.com/tenancy), under *Object storage namespace*|


## Summary of configuration keys for Oracle Functions

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_f | subnet_id |  |yes | Private subnet OCID |
|oracle_f | region | |no | Region name. For example: `eu-madrid-1`. Lithops will use the region set under the `oracle` section if it is not set here |
|oracle_f | docker_server | `<region>.ocir.io` |no | Oracle Container Registry URL. Auto-set to `{region}.ocir.io` from `oracle.region` if not provided |
|oracle_f | docker_user | |no | OCIR login username. Auto-set to `{tenancy_namespace}/{email}` from your OCI user profile when omitted. Format: `<tenancy-namespace>/<username>`. `<username>` is most likely your email address. Set manually for federated accounts |
|oracle_f | docker_password | |yes | OCIR auth token. Required to build and push runtime images. Create one [here](https://cloud.oracle.com/identity/domains/my-profile/auth-tokens). Lithops logs in automatically before pushing runtime images |
|oracle_f | max_workers | 300 | no | Max number of workers. Oracle limits the total to 60 GB RAM across any number of workers  |
|oracle_f | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|oracle_f | runtime |  |no | Runtime name you built and deployed using the Lithops client|
|oracle_f | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|oracle_f | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|oracle_f | runtime_include_function | False | no | If set to true, Lithops will automatically build a new runtime, including the function's code, instead of transferring it through the storage backend at invocation time. This is useful when the function's code size is large (on the order of tens of MB) and the code does not change frequently |


## Test Lithops

Once you have your compute and storage backends configured, you can run a Hello World function with:

```bash
lithops hello -b oracle_f -s oracle_oss
```

## Viewing the execution logs

You can view the function execution logs on your local machine using the *Lithops client*:

```bash
lithops logs poll
```