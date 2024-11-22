# Lithops runtime for AWS EC2

In AWS EC2, you can execute functions using a Virtual Machine (VM). These functions run as parallel processes within the VM. When using Lithops for the first time, there's no need to manually install anything on the remote VMs, as Lithops handles this process automatically. However, utilizing a custom VM is preferable, as employing a pre-built custom image significantly improves overall execution time. To benefit from this approach, follow these steps:

## Option 1:

For building the default VM image that contains all dependencies required by Lithops, execute:

```
lithops image build -b aws_ec2
```

This command will create an image called "lithops-ubuntu-jammy-22.04-amd64-server" in the target region.
If the image already exists, and you want to update it, use the `--overwrite` or `-o` parameter:

```
lithops image build -b aws_ec2 --overwrite
```

Note that if you want to use this default image, there is no need to provide the `target_ami` in the configuration, since lithops automatically looks for this AMI name.

For creating a custom VM image, you can provide an `.sh` script with all the desired commands as an input of the previous command, and you can also provide a custom name:

```
lithops image build -b aws_ec2 -f myscript.sh custom-lithops-runtime
```

If you want to upload local files to the custom VM Image, you can include them using the `--include` or `-i` parameter (src:dst), for example:

```
lithops image build -b aws_ec2 -f myscript.sh -i /home/user/test.bin:/home/ubuntu/test.bin custom-lithops-runtime
```

In the case of using using a custom name, you must provide the `target_ami`, printed at the end of the build command, in your lithops config, for example:

```yaml
aws_ec2:
    ...
    target_ami: <TARGET_AMI>
    ...
```


## Option 2:

You can create a VM image manually. For example, you can create a VM in your AWS region, access the VM, install all the dependencies in the VM itself (apt-get, pip3 install, ...), stop the VM, create a VM Image, and then put the AMI ID in your lithops config, for example:

```yaml
aws_ec2:
    ...
    target_ami: <TARGET_AMI>
    ...
```

Note that if you name your VM Image (AMI) as "lithops-ubuntu-jammy-22.04-amd64-server", there is no need to provide the `target_ami` in the config, since lithops automatically looks for this AMI name.
