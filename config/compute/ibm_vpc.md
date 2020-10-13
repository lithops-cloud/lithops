# Lithops on IBM Virtual Private Cloud service (VPC)

The IBM VPC client is a standalone compute backend. It is used for start and stop VM instances over an IBM VPC automatically when needed.

### Setup

1. Follow [IBM VPC setup](https://cloud.ibm.com/docs/vpc?topic=vpc-creating-a-vpc-using-cli) tutorial to create a VPC, create subnets in one or more regions and to attach a public gateway (using the IBM Cloud CLI).

2. Create a SSH key in [IBM VPC SSH keys UI](https://cloud.ibm.com/vpc-ext/compute/sshKeys).

3. Create an Ubuntu-based virtual server instance (VM) in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) with CPUs and RAM needed for your application.

4. Reserve and associate a floating IP address in [IBM VPC floating IPs UI](https://cloud.ibm.com/vpc-ext/network/floatingIPs) to be used for the virtual server instance.

5. Access to your [security groups](https://cloud.ibm.com/vpc-ext/network/securityGroups) rules and open the port 8080

### Configuration

1. Get your IBM IAM API key, you can create new keys [here](https://cloud.ibm.com/iam/apikeys).

2. Get the floating IP address of your virtual server instance which can be found [here](https://cloud.ibm.com/vpc-ext/network/floatingIPs).

3. Get the endpoint of your subnet region, endpoint URLs list can be found [here](https://cloud.ibm.com/apidocs/vpc#endpoint-url).

4. Get the virtual server instance ID by selecting on your instance in [IBM VPC virtual server instances UI](https://cloud.ibm.com/vpc-ext/compute/vs) and then extracting from the instance's details.

5. Edit your lithops config and add the relevant keys:

   ```yaml
   lithops:
       executor: standalone

   ibm:
       iam_api_key: <iam-api-key>

   ibm_vpc:
       endpoint: <endpoint>
       instance_id: <instance-id>
       ip_address: <floating-ip-address>
   ```
   
#### Summary of configuration keys for IBM VPC

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|ibm_vpc | endpoint | |yes | Endpoint of your subnet region |
|ibm_vpc | instance_id | |yes | virtual server instance ID |
|ibm_vpc | ip_address | |yes | Floatting IP address atached to your Vm instance|
|ibm_vpc | version | | no | Use for specifying IBM VPC production application version date, it is recommended to configure it statically |
|ibm_vpc | generation | 2 | no | Use for specifying IBM VPC environment compute generation, see [Comparing compute generations in VPC](https://cloud.ibm.com/docs/cloud-infrastructure?topic=cloud-infrastructure-compare-vpc-vpcoc) for additional information |
|ibm_vpc | ssh_user | root |no | Username to access the VM |
|ibm_vpc | ssh_key_filename | | no | Path to the ssh key file provided to create the VM. It will use the default path if not provided |
