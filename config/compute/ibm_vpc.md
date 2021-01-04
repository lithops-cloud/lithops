# Lithops and IBM Virtual Private Cloud

The IBM VPC client of Lithops can provide a truely serverless user experience on top of IBM VPC where Lithops creates new VM instances dynamically in runtime and scale Lithops jobs against generated VMs. Alternatively Lithops can start and stop existing VM instances.

## IBM VPC
The assumption that you already familiar with IBM Cloud, have your IBM IAM API key created (you can create new keys [here](https://cloud.ibm.com/iam/apikeys)), have valid IBM COS account, region and resource group.

Follow [IBM VPC setup](https://cloud.ibm.com/vpc-ext/overview) if you need to create IBM Virtual Private Cloud. Decide the region for your VPC. The best practice is to use the same region both for VPC and IBM COS, hoewever there is no requirement to keep them in the same region.

### The following is the minimum setup requirements

1.	Create new VPC if you don't have one already. More details [here](https://cloud.ibm.com/vpc-ext/network/vpcs)
2. Create new subnet with public gateway and IP range and total count. More details [here](https://cloud.ibm.com/vpc-ext/network/subnets)
3. Create new access contol list. More details [here](https://cloud.ibm.com/vpc-ext/network/acl)
4. Create security group for your resource group. More details [here](https://cloud.ibm.com/vpc-ext/network/securityGroups)
5. Create a SSH key in [IBM VPC SSH keys UI](https://cloud.ibm.com/vpc-ext/compute/sshKeys)


## Lithops and the VM auto create mode
In this mode Lithops will automatically, dynamically in runtime create new VM instances, scale Lithops job against generated VMs and automatically delete VMs when job completed.

The partitioning logic on number of VMs is based on the input dataset and is the same logic for other backends.  The following example further demonstrates this

	iterdata = [1, 2, 3, 4]

	def my_map_function(x):
		return x + 7

	if __name__ == '__main__':
		pw lithops.FunctionExecutor()
		pw.map(my_map_function, iterdata)
		print (pw.get_result())

The input set is of length 4. Lithops in the auto create mode, will create 4 different VMs so each VM will execute `my_map_function` with different values of the `iterdata`.

### Lithops configuration for auto create mode

Edit your lithops config and add the relevant keys:

   ```yaml
   lithops:
		mode: standalone

   ibm:
		iam_api_key: <iam-api-key>

	standalone:
		backend: ibm_vpc
		exec_mode: create

   ibm_vpc:
		endpoint: <REGION_ENDPOINT>
		ssh_user: <SSH USER>
		ssh_key_filename: <PATH TO id_rsa.pub>
		security_group_id: <SECURITY_GROUP_ID>
		subnet_id: <SUBNET_ID>
		key_id: <PUBLIC_KEY_ID>
		resource_group_id: <RESOURCE_GROUP_ID>
		vpc_id: <VPC_ID>
		image_id: <IMAGE_ID>
		zone_name: <ZONE_NAME>
		volume_tier_name: <VOLUME_TIER_NAME>  # Optional
		profile_name: <PROFILE_NAME>  # Optional

   ```

The fastest way to find all the required keys for `ibm_vpc` section as follows:

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


Your lithops config ibm_vpc section should now look like:

    ```yaml

    ibm_vpc:
		endpoint: https://us-south.iaas.cloud.ibm.com
		ssh_user: <SSH USER>
		ssh_key_filename: <PATH TO id_rsa.pub>
		security_group_id: r006-2d3cc459-bb8b-4ec6-a5fb-28e60c9f7d7b
		subnet_id: 0737-bbc80a8f-d46a-4cc6-8a5a-991daa5fc914
		key_id: r006-14719c2a-80cf-4043-8018-fa22d4ce1337
		resource_group_id: 8145289ddf7047ea93fd2835de391f43
		vpc_id: r006-afdd7b5d-059f-413f-a319-c0a38ef46824
		image_id: r006-988caa8b-7786-49c9-aea6-9553af2b1969
		zone_name: us-south-3
		volume_tier_name: 10iops-tier
		profile_name: bx2-8x32
    ```

### Verify auto create mode with Lithops

To verify auto create mode is working, use the following example

	iterdata = [1]

	def my_map_function(x):
		return x + 7

	if __name__ == '__main__':
		pw lithops.FunctionExecutor()
		pw.map(my_map_function, iterdata)
		print (pw.get_result())

This will create a single VM instance and execute `my_map_function` in the created VM. Upon completion, Lithops will delete the VM.

####  Important information
1. The first time you use Lithops with specific runtime, Lithops will try generate and obtain runtime metadata. For this purpose Lithops will create a VM, extract specific metadata and delete VM. All further executions against same runtime will skip this step as runtime metadata will be cached both locally and in IBM COS.
2. In certain cases where ssh access details are wrong, Lithops might fail to ssh into created VM from the previous step. In this case, fix the ssh access credentials, navigate into dashboard of IBM VPC and manually delete the VM and floating IP associated with it.
3.	The first time you deplopy Lithops job in the auto create mode it is advised to navigate to dashboard of IBM VPC and verify that VM is being created and deleted.

### Verify auto create mode with Lithops with multiple VMs

To verify auto create mode is working, use the following example

	iterdata = [1,2,3,4]

	def my_map_function(x):
		return x + 7

	if __name__ == '__main__':
		pw lithops.FunctionExecutor()
		pw.map(my_map_function, iterdata)
		print (pw.get_result())

This will create 4 different VM instance and execute `my_map_function` in the each of created VM. Upon completion, Lithops will delete the VMs.

## Lithops in a standalone mode

In this mode, Lithops can start and stop existing VM and deploy an entire job to that VM. The partition logic in this scenario is different from the auto create mode, since entire job executed in the same VM. As example

	iterdata = [1, 2, 3, 4]

	def my_map_function(x):
		return x + 7

	if __name__ == '__main__':
		pw lithops.FunctionExecutor()
		pw.map(my_map_function, iterdata)
		print (pw.get_result())

The input set is of length 4. Lithops in the standalone mode, will start a single VM and invoke 4 different Docker containers, each executing `my_map_function` with different values of the `iterdata`.

### Lithops configuration for the standalone mode

Edit your lithops config and add the relevant keys:

   ```yaml
   lithops:
		mode: standalone

   ibm:
		iam_api_key: <iam-api-key>

	standalone:
		backend: ibm_vpc
		exec_mode: create

   ibm_vpc:
		endpoint    : <REGION_ENDPOINT>
		ssh_user: <SSH USER>
		ssh_key_filename: <PATH TO id_rsa.pub>
		ip_address  : <FLOATING IP ADDRESS OF THE VM>
		instance_id : <INSTANCE ID OF THE VM>

   ```
If you need to create new VM, then follow the steps to create and update Lithops configuration:

1. Create an Ubuntu 20.04 virtual server instance (VM) in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) with CPUs and RAM needed for your application.

2. Reserve and associate a floating IP address in [IBM VPC floating IPs UI](https://cloud.ibm.com/vpc-ext/network/floatingIPs) to be used for the virtual server instance.

3. Get the floating IP address of your virtual server instance which can be found [here](https://cloud.ibm.com/vpc-ext/network/floatingIPs).

4. Get the endpoint of your subnet region, endpoint URLs list can be found [here](https://cloud.ibm.com/apidocs/vpc#endpoint-url).

5. Get the virtual server instance ID by selecting on your instance in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) and then extracting from the instance's details.

### Veiwing invocation logs

You can view the executions logs in your local machine using the *lithops client*:

```bash
$ lithops logs poll
```
## Summary of the configuration keys

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
