# Lithops runtime for IBM VPC

In IBM VPC, you can execute functions using a Virtual Machine (VM). These functions operate through parallel processes within the VM. When utilizing Lithops for the first time, there's no need to manually install anything on the remote VMs, as Lithops handles this process automatically. However, employing a custom VM is recommended, as utilizing a pre-built custom image significantly enhances overall execution time. To implement this approach effectively, follow these steps:

## Option 1:

For building the default VM image that contains all dependencies required by Lithops, execute:

```
lithops image build -b ibm_vpc
```

This command will create an image called "lithops-ubuntu-22-04-3-minimal-amd64-1" in the target region.
If the image already exists, and you want to updete it, use the `--overwrite` or `-o` parameter:

```
lithops image build -b ibm_vpc --overwrite
```

Note that if you want to use this default image, there is no need to provide the image ID in the configuration, since Lithops will automatically look for it.

For creating a custom VM image, you can provide an `.sh` script with all the desired commands as an input of the previous command, and you can also provide a custom name:

```
lithops image build -b ibm_vpc -f myscript.sh custom-lithops-runtime
```

If you want to upload local files to the custom VM Image, you can include them using the `--include` or `-i` parameter (src:dst), for example:

```
lithops image build -b ibm_vpc -f myscript.sh -i /home/user/test.bin:/home/ubuntu/test.bin custom-lithops-runtime
```

In the case of using using a custom name, you must provide the Image ID, printed at the end of the build command, in your lithops config, for eaxmple:

```yaml
ibm_vpc:
    ...
    image_id: <IMAGE_ID>
    ...
```

## Option 2:

You can create a VM image manually. For example, you can create a VM in you AWS region, access the VM, install all the dependencies in the VM itself (apt-get, pip3 install, ...), stop the VM, create a VM Image, and then put the image_id in your lithops config, for example:

```yaml
ibm_vpc:
    ...
    image_id: <IMAGE_ID>
    ...
```

## Option 3 (Discontinued):

For building the VM image that contains all dependencies required by Lithops, execute the [build script](build_lithops_runtime.sh) located in this folder. The best is to use vanilla Ubuntu machine to run this script and this script will use a base image based on **ubuntu-20.04-server-cloudimg-amd64**. There is need to have sudo privileges to run this script.
Once you accessed the machine, download the script

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


### Deploy the image

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
