# Lithops runtime for Google Compute Engine

In Google Compute Engine (GCE), Lithops runs functions as parallel processes inside VMs. On first use, Lithops can install all dependencies on each VM automatically, but that adds several minutes to every cold start. A pre-built custom image avoids that cost.

The Lithops backend key is `gcp_compute_engine` (matches the module name).

Custom images are based on the default Ubuntu 24.04 LTS image: `projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64`.

## Option 1: Build the default Lithops image

Build the default VM image with all Lithops dependencies:

```bash
lithops image build -b gcp_compute_engine
```

This creates an image named `lithops-ubuntu-2404-lts-amd64-server` in your GCP project.

To rebuild when the image already exists:

```bash
lithops image build -b gcp_compute_engine --overwrite
```

If you use this default image name, you do not need to set `source_image` in the config; Lithops discovers it automatically.

List available Ubuntu and Lithops images:

```bash
lithops image list -b gcp_compute_engine
```

Use the **Image ID** column as `source_image` when you use a custom image name.

### Custom image name and extra setup

Provide an install script and optional image name:

```bash
lithops image build -b gcp_compute_engine -f myscript.sh custom-lithops-runtime
```

Upload local files into the image with `--include` / `-i` (`src:dst`):

```bash
lithops image build -b gcp_compute_engine -f myscript.sh \
  -i /home/user/test.bin:/home/ubuntu/test.bin custom-lithops-runtime
```

When using a custom name, set `source_image` in your Lithops config to the value printed at the end of the build (for example `projects/<PROJECT_ID>/global/images/custom-lithops-runtime`):

```yaml
gcp_compute_engine:
  project_name: <PROJECT_ID>
  zone: us-central1-a
  source_image: projects/<PROJECT_ID>/global/images/custom-lithops-runtime
```

Delete a custom image:

```bash
lithops image delete -b gcp_compute_engine <image-name>
```

## Option 2: Manual image

Create a VM from Ubuntu 24.04, install dependencies (apt, pip, Lithops, Redis, Docker as needed), stop the VM, then create a custom image in the GCP console or with `gcloud compute images create`. Set `source_image` in your config to the full image resource path.

If you name the image `lithops-ubuntu-2404-lts-amd64-server`, Lithops picks it up without an explicit `source_image` entry.
