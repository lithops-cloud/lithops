# Oracle Functions (beta)

Lithops with *Oracle Functions* as serverless compute backend.

**Note**: This is a beta backend. Please open an issue if you encounter any error/bug

## Installation

1. Install Oracle Cloud backend dependencies:
```
python3 -m pip install lithops[oracle]
```

2. Access to your [Oracle Cloud Console](https://cloud.oracle.com/) and activate your Functions service instance.

## Configuration


### Creating a Dynamic Group

1. **Sign in to the Oracle Cloud Console.** 

2. **Open the navigation menu.** Under Identity & Security , go to Polices and then click **Domains**.

3. Click on the current Domain (It's called **Default** by default) and then click on **Dynamic groups**

3. **Click Create Dynamic Group.**

4. **In the Create Dynamic Group dialog box:**

    - Give your dynamic group a **Name** and **Description**.
  
    - In the **Matching Rule** box, paste your rule:

        ```
        ALL {resource.type = 'fnfunc', resource.compartment.id = 'ocid1.tenancy.oc1..aaaaaaaaedomxxeig7qoo5fmbbvkdlbmp6dsdl74sh2so32zk3wxnc2dosla'}
        ```
    
5. **Click Create** to create the dynamic group.

### Creating a Policy for the Dynamic Group

Now that the dynamic group is set up, you'll need to create a policy that allows this group to manage resources.

1. **Open the navigation menu again.** Under Governance and Administration, go to Identity, and then click **Policies**.

2. **Choose your compartment.**

3. **Click on the Create Policy button.**

4. **In the Create Policy dialog box:**

    - Give your policy a **Name** and **Description**.
    
    - In the **Statement** box, input the policy statement that grants permissions. For example:

        ```
        Allow dynamic-group function_compartment to manage all-resources in tenancy
        ```
    
    Remember to replace `function_compartment` with the name of the dynamic group you just created.
    
5. **Click Create** to create the policy.

Now, your Oracle Functions have the necessary permissions to manage resources in your Oracle Cloud Infrastructure tenancy.

1. Navigate to the Oracle Cloud Console. If you haven't already done so, follow the instructions in the Oracle documentation to generate and download the necessary API signing keys.

2. Access your Oracle Functions dashboard, and choose your preferred region.

3. Create a new subnet in the Virtual Cloud Network (VCN) section. If you haven't set up a subnet yet, follow the instructions in the Oracle documentation to create one. Subnet creation is mandatory.

4. Edit your Lithops config and add the following keys:

```yaml
lithops:
    backend: oracle_f

oracle:
    user : <USER>
    key_file : <KEY_FILE>
    fingerprint : <FINGERPRINT>
    tenancy : <TENANCY>
    region : <REGION>
    compartment_id: <COMPARTMENT_ID>
    namespace_name : <NAMESPACE_NAME>

oracle_f:
    runtime: <RUNTIME>
    runtime_memory: <RUNTIME_MEMORY>
    vcn:
        subnet_ids:
            <SUBNET_ID 1>
```

Also, remember to login into your Oracle container registry before you build your runtime. This is because runtimes are uploaded to the Oracle container registry.

```
docker login region.ocir.io -u namespace_name/username -p authentication_token
```
## Summary of configuration keys for Oracle:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle | user | |yes |  Oracle Cloud User's OCID |
|oracle | key_file | |yes | Path to the PEM file |
|oracle | fingerprint | |yes | Fingerprint of the PEM file |
|oracle | tenancy | |yes | Tenancy's OCID |
|oracle | region | |yes | Region name. For example: `eu-madrid-1` |
|oracle | compartment_id | |yes | Compartment's OCID |
|oracle | namespace_name | |yes | Namespace name for the container registry where docker images are uploaded |


## Summary of configuration keys for Oracle Functions :

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_f | region | |no | Region name. For example: `eu-west-1`. Lithops will use the region set under the `oracle` section if it is not set here |
|oracle_f | max_workers | 300 | no | Max number of workers. Oracle limits to 60 GB RAM, any number of workers  |
|oracle_f | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|oracle_f | runtime |  |no | Runtime name you built and deployed using the lithops client|
|oracle_f | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|oracle_f | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|oracle_f | vcn |  |yes | VCN Configuration |



## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b oracle_f -s oracle_oss
```
