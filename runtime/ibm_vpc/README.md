# Lithops runtime for IBM VPC

In IBM VPC, you can run functions by using a Virtual machine (VM). In the VM, functions run using parallel processes. In this case, it is not needed to install anything in the remote VMs since Lithops does this process automatically the first time you use them. However, use a custom VM it is a preferable approach, since using a pre-built custom image will greatly improve the overall execution time. To benefit from this approach, follow the following steps:

## Build the custom image
For building the VM image that contains all dependencies required by Lithops, execute the [build script](build_lithops_runtime.sh) located in this folder. The best is to use vanilla Ubuntu machine to run this script and this script will use a base image based on **ubuntu-20.04-server-cloudimg-amd64**. There is need to have sudo privileges to run this script. We advice to create a new VSI in VPC with minimal setup, like `cx2-2x4`, setup floating IP for this machine and use it to build custom image. Once you accessed the machine, download the script

    wget https://raw.githubusercontent.com/lithops-cloud/lithops/master/runtime/ibm_vpc/build_lithops_vm_image.sh

and make it executable with

    chmod +x build_lithops_vm_image.sh

### Build the Image with Docker runtime

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

### Build the Image without a Docker runtime
Alternative is to build a VM image without a Docker runtime. This approach is mainly focused to run Lithops functions within the VM in the python3 interpreter, without using a docker runtime. If you plant to use a docker runtime to run the functions within the VM, consider to follow the previous approach. The default `build_lithops_vm_image.sh` file contains contains all required dependencies for Lithops. If you need extra linux packages and python libraries, you must edit the `build_lithops_vm_image.sh` file and include all them.

 ```
 $ ./build_lithops_vm_image.sh lithops-ubuntu-20.04.qcow2
 ```
In this example the script generates a VM image named `lithops-ubuntu-20.04.qcow2` that contains all dependencies required by Lithops.


## Deploy the image

Once local image is ready you need to upload it to COS. The best would be to use the `lithops storage` CLI:

1. Upload the `lithops-ubuntu-20.04.qcow2` image to your IBM COS instance, and place it under the root of a bucket

    ```
    lithops storage put lithops-ubuntu-20.04.qcow2 your-bucket-name
    ```

2. Grant permissions to the IBM VPC service to allow access to your IBM Cloud Object Storage instance

   * Get the GUID of your cloud object storage account by running the next command: 
     ```
     $ ibmcloud resource service-instance "cloud-object-storage-instance-name"
     ```
   * Create the authorization policy
     ```
     $ ibmcloud iam authorization-policy-create is cloud-object-storage Reader --source-resource-type image \
          --target-service-instance-id "cos-guid"
     ```

3. [Navigate to IBM VPC dashboard, custom images](https://cloud.ibm.com/vpc-ext/compute/images) and follow instructions to create new custom image based on the `lithops-ubuntu-20.04.qcow2`

4. **Clean everything**

    You can clean everything related to Lithops, such as all deployed workers and cache information, and start from scratch by simply running the next command (Configuration is not deleted):
    ```
    $ lithops clean -b ibm_vpc
    ```
    In order to delete also master VM use `--all` flag
    ```
    $ lithops clean -b ibm_vpc --all
    ```
    In order to delete also master floating ip VM add `--force` flag
    ```
    $ lithops clean -b ibm_vpc --all --force
    ```
