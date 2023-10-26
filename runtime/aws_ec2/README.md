# Lithops runtime for AWS EC2

In AWS EC2, you can run functions by using a Virtual machine (VM). In the VM, functions run using parallel processes. In this case, it is not needed to install anything in the remote VMs since Lithops does this process automatically the first time you use them. However, use a custom VM it is a preferable approach, since using a pre-built custom image will greatly improve the overall execution time. To benefit from this approach, follow the following steps:

## Option 1 (beta):

**Note**: This is a beta feature. Please open an issue if you encounter any errors using this way of creating VM images in AWS EC2.

For building the default VM image that contains all dependencies required by Lithops, execute:

```
lithops image build -b aws_ec2
```

This command will create an image called "lithops-ubuntu-jammy-22.04-amd64-server" in the target region.
If the image already exists, and you want to updete it, use the '--overwrite' or '-o' flag:

```
lithops image build -b aws_ec2 --overwrite
```

Note that if you want to use this default image, there is no need to provide the `target_ami` in the configuration, since lithops automatically looks for this AMI name.

For creating a custom VM image, you can provide an `.sh` script with all the desired commands as an input of the previous command, and you can also provide a custom name:

```
lithops image build -b aws_ec2 -f myscript.sh custom-lithops-runtime
```

In this case, if you use a custom name, you must provide the `target_ami`, printed at the end of the build command, in your lithops config:

```yaml
aws_ec2:
    ...
    target_ami: <TARGET_AMI>
    ...
```


## Option 2:

You can create a VM image manually. For example, you can create a VM in you AWS region, access the VM, install all the dependencies in the VM itself (apt-get, pip3 install, ...), stop the VM, create a VM Image, and then put the image_id in your lithops config file:

```yaml
aws_ec2:
    ...
    target_ami: <TARGET_AMI>
    ...
```

Note that if you name your VM Image (AMI) as "lithops-worker-default", there is no need to provide the `target_ami` in the config, since lithops automatically looks for this AMI name.
