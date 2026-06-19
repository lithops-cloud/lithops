# Lithops runtime for IBM VPC

In IBM VPC, Lithops runs functions as parallel processes inside Virtual Server Instances (VSIs). On first use, Lithops can install all dependencies on each VM automatically, but that adds several minutes to every cold start. A pre-built custom image avoids that cost.

The Lithops backend key is `ibm_vpc`.

By default Lithops provisions VSIs from the IBM stock image **`ibm-ubuntu-24-*-minimal-amd64-*`** (Ubuntu 24.04 LTS). Ubuntu 26 and other versions are not selected automatically.

## Option 1: Build the default Lithops image

Build the default VM image with all Lithops dependencies:

```bash
lithops image build -b ibm_vpc
```

This creates an image named **`lithops-ubuntu-24-04-4-minimal-amd64-1`** in your IBM VPC region.

To rebuild when the image already exists:

```bash
lithops image build -b ibm_vpc --overwrite
```

If you use this default image name, you do not need to set `image_id` in the config; Lithops discovers it automatically.

List available Ubuntu and Lithops images:

```bash
lithops image list -b ibm_vpc
```

Use the **Image ID** column as `image_id` when you use a custom image name.

### Custom image name and extra setup

Provide an install script and optional image name:

```bash
lithops image build -b ibm_vpc -f myscript.sh custom-lithops-runtime
```

Upload local files into the image with `--include` / `-i` (`src:dst`):

```bash
lithops image build -b ibm_vpc -f myscript.sh \
  -i /home/user/test.bin:/home/ubuntu/test.bin custom-lithops-runtime
```

When using a custom name, set `image_id` in your Lithops config to the value printed at the end of the build:

```yaml
ibm_vpc:
  image_id: <IMAGE_ID>
```

Delete a custom image:

```bash
lithops image delete -b ibm_vpc <image-name>
```

## Option 2: Manual image

Create a VSI from an IBM Ubuntu **24.04** image (`ibm-ubuntu-24-*-minimal-amd64-*`), install dependencies (apt, pip, Lithops, Redis, Docker as needed), stop the VSI, then create a custom image from the [IBM VPC images console](https://cloud.ibm.com/vpc-ext/compute/images). Set `image_id` in your config:

```yaml
ibm_vpc:
  image_id: <IMAGE_ID>
```

If you name the image `lithops-ubuntu-24-04-4-minimal-amd64-1`, Lithops picks it up without an explicit `image_id` entry.

## SSH access

IBM Ubuntu images use the **`ubuntu`** SSH user (not `root`). Lithops sets this by default in `ibm_vpc.ssh_username`.

## Option 3 (legacy): Manual qcow2 build

The [build_lithops_vm_image.sh](build_lithops_vm_image.sh) script builds a qcow2 from the Ubuntu **24.04** cloud image for manual upload to IBM COS and registration as a custom VPC image. This path is deprecated in favour of `lithops image build -b ibm_vpc`, but remains available for advanced use.

Run the script on a vanilla Ubuntu machine with sudo privileges. Requirements: `libguestfs-tools`, `qemu-img`, and `expect`.

Download the script if needed:

```bash
wget https://raw.githubusercontent.com/lithops-cloud/lithops/master/runtime/ibm_vpc/build_lithops_vm_image.sh
chmod +x build_lithops_vm_image.sh
```

### Build the image with a Docker runtime

If you plan to run functions within a **docker runtime** in the VM, bake the Docker image into the VM image to avoid `docker pull` on every cold start. Add the `-d` flag followed by the Docker image name:

```bash
./build_lithops_vm_image.sh -d lithopscloud/ibmcf-python-v312 lithops-ubuntu-24.04.qcow2
```

**Important:** Lithops will include all local Docker images together with the Lithops runtime. To include only the Lithops runtime, delete all local Docker images first or run the script on a clean Ubuntu 24.04 VM. To prune local images before baking:

```bash
./build_lithops_vm_image.sh -p prune -d lithopscloud/ibmcf-python-v312 lithops-ubuntu-24.04.qcow2
```

### Build the image without a Docker runtime

To run Lithops functions with the VM `python3` interpreter (no Docker runtime), build without `-d`:

```bash
./build_lithops_vm_image.sh lithops-ubuntu-24.04.qcow2
```

The default `build_lithops_vm_image.sh` installs Lithops dependencies. To add extra Linux or Python packages, edit the script before running it.

### Deploy the image

Once the local qcow2 image is ready, upload it to IBM COS and register it as a custom VPC image:

1. Upload `lithops-ubuntu-24.04.qcow2` to your IBM COS bucket:

   ```bash
   lithops storage put lithops-ubuntu-24.04.qcow2 your-bucket-name
   ```

2. Grant IBM VPC permission to read your COS instance:

   * Get the GUID of your Cloud Object Storage instance:

     ```bash
     ibmcloud resource service-instance "cloud-object-storage-instance-name"
     ```

   * Create the authorization policy:

     ```bash
     ibmcloud iam authorization-policy-create is cloud-object-storage Reader \
       --source-resource-type image \
       --target-service-instance-id "cos-guid"
     ```

3. [Navigate to IBM VPC custom images](https://cloud.ibm.com/vpc-ext/compute/images) and create a new custom image from `lithops-ubuntu-24.04.qcow2`.
