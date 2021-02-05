# Lithops runtime for IBM VPC

In IBM VPC, you can run functions by using a Virtual machine (VM). In the VM, functions run using parallel processes. In this case, it is not needed to install anything in the remote VMs since Lithops does this process automatically the first time you use them. Howvere, use a custom Vm it is a preferable approach use, since using a pre-built custom image will greatly improve the overllal execution time. To benefit from this approach, follow the following steps:

1. Execute the build [script](ubuntu-20.04-server-cloudimg-amd64.sh). You need an Ubuntu machine to run this script and this script will use a base image based on ubuntu-20.04-server-cloudimg-amd64. There is need to have sudo priveleges to run this script. Once script finished it will generate `ubuntu2004srv.qcow2` that contains all dependecies required by Lithops.

2. Upload `ubuntu2004srv.qcow2` to the IBM COS, and place it under the root of a bucket

4. Grant permissions to the IBM VPC service to allow access to your IBM Cloud Object Storage instance

   * Get the GUID of your cloud object storage account by running the next command: 
     ```
     $ ibmcloud resource service-instance "Cloud object Storage instance name"
     
     ```
   * Create the authorization policy
      ```
      $ ibmcloud iam authorization-policy-create is cloud-object-storage Reader --source-resource-type image --target-service-instance-id GUID
     
      ```

3. [Navigate to IBM VPC dashboard, custom images](https://cloud.ibm.com/vpc-ext/compute/images) and follow instructions to create new custom image based on the `ubuntu2004srv.qcow2`
