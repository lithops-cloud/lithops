# Lithops on IBM Virtual Private Cloud service (VPC)

The IBM VPC client is a standalone compute backend. It is used for start and stop VM instances over an IBM VPC automatically when needed.

### Setup

1. Follow [IBM VPC setup](https://cloud.ibm.com/docs/vpc?topic=vpc-creating-a-vpc-using-cli) tutorial to create a VPC, create subnets in one or more regions and to attach a public gateway (using the IBM Cloud CLI).

2. Create a SSH key in [IBM VPC SSH keys UI](https://cloud.ibm.com/vpc-ext/compute/sshKeys).

3. Create an Ubuntu 20.04 virtual server instance (VM) in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) with CPUs and RAM needed for your application.

4. Reserve and associate a floating IP address in [IBM VPC floating IPs UI](https://cloud.ibm.com/vpc-ext/network/floatingIPs) to be used for the virtual server instance.

### Configuration

1. Get your IBM IAM API key, you can create new keys [here](https://cloud.ibm.com/iam/apikeys).

2. Get the floating IP address of your virtual server instance which can be found [here](https://cloud.ibm.com/vpc-ext/network/floatingIPs).

3. Get the endpoint of your subnet region, endpoint URLs list can be found [here](https://cloud.ibm.com/apidocs/vpc#endpoint-url).

4. Get the virtual server instance ID by selecting on your instance in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) and then extracting from the instance's details.

5. Edit your lithops config and add the relevant keys:

   ```yaml
   lithops:
       mode: standalone

   ibm:
       iam_api_key: <iam-api-key>

   ibm_vpc:
       endpoint: <endpoint>
       instance_id: <instance-id>
       ip_address: <floating-ip-address>
   ```

### Usage

Note that the first time you execute a job in a brand new VM instance, the initial installation process can take up to ~3 minutes. 

You can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```

#### Summary of configuration keys for IBM VPC

The fastest way to find all the required keys is following:

1. Login to IBM Cloud and open up your [dashboard](https://cloud.ibm.com/).

2. Navigate to your [IBM VPC create instance](https://cloud.ibm.com/vpc-ext/provision/vs).

3. On the left, fill all the parameters required for your new VM instance creation: name, resource group, location, image, ssh key and vpc

4. On the right, click `Get sample API call`.

5. Copy to clipboard the code from the `REST request: Creating a virtual server instance` dialog and paste to your favorite editor.

6. Close the `Create instance` window without creating it.

7. In the code, find `security_groups` section and paste its `id` value to the .lithops_config ibm_vpc section security_group_id key.

8. Find `subnet` section and paste its `id` value to the .lithops_config ibm_vpc section subnet_id key.

9. Find `keys` section and paste its `id` value to the .lithops_config ibm_vpc section key_id key.

10. Find `resource_group` section and paste its `id` value to the .lithops_config ibm_vpc section resource_group_id key.

11. Find `vpc` section and paste its `id` value to the .lithops_config ibm_vpc section vpc_id key.

12. Find `image` section and paste its `id` value to the .lithops_config ibm_vpc section image_id key.

13. Find `zone` section and paste its `name` value to the .lithops_config ibm_vpc section zone_name key.

14. Set `delete_on_dismantle` to `True` in order to delete VM with all its resource on dismantle instead of stop 

Your lithops config ibm_vpc section should look like:

    ```yaml
    ibm_vpc:
        endpoint    : <REGION_ENDPOINT>
        instance_id : <INSTANCE_ID>	    # Optional
        ip_address  : <FLOATING_IP_ADDRESS>	   # Optional
        security_group_id: <SECURITY_GROUP_ID>
        subnet_id: <SUBNET_ID>
        key_id: <PUBLIC_KEY_ID>
        resource_group_id: <RESOURCE_GROUP_ID>
        vpc_id: <VPC_ID>
        image_id: <IMAGE_ID>
        zone_name: <ZONE_NAME>
        volume_tier_name: <VOLUME_TIER_NAME>  # Optional
        profile_name: <PROFILE_NAME>  # Optional
        delete_on_dismantle: False  # Optional
    ```

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | endpoint | |yes | Endpoint of your subnet region |
|ibm_vpc | instance_id | | no | virtual server instance ID |
|ibm_vpc | ip_address | | no | Floatting IP address atached to your Vm instance|
|ibm_vpc | version | | no | Use for specifying IBM VPC production application version date, it is recommended to configure it statically |
|ibm_vpc | generation | 2 | no | Use for specifying IBM VPC environment compute generation, see [Comparing compute generations in VPC](https://cloud.ibm.com/docs/cloud-infrastructure?topic=cloud-infrastructure-compare-vpc-vpcoc) for additional information |
|ibm_vpc | ssh_user | root |no | Username to access the VM |
|ibm_vpc | ssh_key_filename | | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
|ibm_vpc | security_group_id | | yes | Security group id |
|ibm_vpc | subnet_id | | yes | Subnet id |
|ibm_vpc | key_id | | yes | Ssh public key id |
|ibm_vpc | resource_group_id | | yes | Resource group id |
|ibm_vpc | vpc_id | | yes | VPC id |
|ibm_vpc | image_id | | yes | Virtual machine image id |
|ibm_vpc | zone_name | | yes | Zone name |
|ibm_vpc | volume_tier_name | | no | Virtual machine volume tier |
|ibm_vpc | profile_name | | no | Virtual machine profile name |
|ibm_vpc | delete_on_dismantle | | no | If True delete VM resource when dismantled |
