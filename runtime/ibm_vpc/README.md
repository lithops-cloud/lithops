# Lithops runtime for IBM VPC

In IBM VPC, you can run functions by using a Virtual machine (VM). In the VM, functions run using parallel processes. In this case, it is not needed to install anything in the remote VMs since Lithops does this process automatically the first time you use them. However, use a custom VM it is a preferable approach, since using a pre-built custom image will greatly improve the overall execution time. To benefit from this approach, follow the following steps:

## Build the custom image
For building the VM image that contains all dependencies required by Lithops, execute the [build script](build_lithops_runtime.sh) located in this folder. The best to use vanilla Ubuntu machine to run this script and this script will use a base image based on **ubuntu-20.04-server-cloudimg-amd64**. There is need to have sudo privileges to run this script. We advice to create a new VSI in VPC with minimal setup, like `cx2-2x4`, setup floating IP for this machine and use it to build custom image. Once you accessed the machine, download the script

    wget https://raw.githubusercontent.com/lithops-cloud/lithops/master/runtime/ibm_vpc/build_lithops_vm_image.sh

and make it executable with

    chmod +x build_lithops_vm_image.sh

### Build the Image with Lithops runtime

If you plan to run your function within a **docker runtime** in the VM, it is preferable to include the docker image into the VM image. In this way, you will avoid the initial `docker pull <image/name>` command, thus reducing the overall execution time. To do so, add the `-d` flag followed by the docker image name you plant to use, for example:

 ```
 $ ./build_lithops_vm_image.sh -d lithopscloud/ibmcf-python-v38 lithops-ubuntu-20.04.qcow2
 ```
**Important**

Lithops will include all the local Docker images together with the Lithops runtime. To avoid this and include only Lithops runtime, it's adviced to delete all local Docker images or run the script in a vanilla Ubuntu 20.04 VM. To delete all local images and include only Lithops runtime you need to execute

```
 $ ./build_lithops_vm_image.sh -p prune -d lithopscloud/ibmcf-python-v38  lithops-ubuntu-20.04.qcow2
```

In this example the script generates a VM image named `lithops-ubuntu-20.04.qcow2` that contains all dependencies required by Lithops.

### Build the Image without Lithops runtime
Alternative is to build image without Lithops runtime. This approach is less preferable. In this approach you build custom image that contains all required dependecies for Lithops. However this doesn't include Lithops runtime. In this approach Lithops will pull Lithops runtime during job execution and it will not be part of the image

 ```
 $ ./build_lithops_vm_image.sh lithops-ubuntu-20.04.qcow2
 ```
In this example the script generates a VM image named `lithops-ubuntu-20.04.qcow2` that contains all dependencies required by Lithops.


## Deploy the image

Once local image is ready you need to upload it to COS. The best would be to use `rclone` tool

1. Install [rclone](https://rclone.org/install/)
2. Edit configuration file as shown by command `rclone config file` and add the following entry

        [COS]
        type = s3
        provider = IBMCOS
        env_auth = false
        access_key_id = <COS_ACCESS_KEY>
        secret_access_key = <COS_SECRET_KEY>
        endpoint = <COS_ENDPOINT> # for example: s3.us-east.cloud-object-  storage.appdomain.cloud

3. Upload the `lithops-ubuntu-20.04.qcow2` image to your IBM COS instance, and place it under the root of a bucket

        rclone -P --log-level INFO copy lithops-ubuntu-20.04.qcow2 COS:<YOUR BUCKET>/

2. Grant permissions to the IBM VPC service to allow access to your IBM Cloud Object Storage instance

   * Get the GUID of your cloud object storage account by running the next command: 
     ```
     $ ibmcloud resource service-instance "Cloud object Storage instance name"
     ```
   * Create the authorization policy
     ```
     $ ibmcloud iam authorization-policy-create is cloud-object-storage Reader --source-resource-type image \
          --target-service-instance-id GUID
     ```

3. [Navigate to IBM VPC dashboard, custom images](https://cloud.ibm.com/vpc-ext/compute/images) and follow instructions to create new custom image based on the `lithops-ubuntu-20.04.qcow2`
