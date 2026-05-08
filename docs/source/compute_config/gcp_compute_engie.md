# Google Compute Engine (GCE)

Lithops includes a standalone backend named `gcp_compute_engie` for running jobs on Google Compute Engine virtual machines.

This backend supports:

- **consume mode**: use an existing VM instance.
- **create mode**: create the network resources and master/worker VMs on demand.
- **reuse mode**: keep and reuse workers between executions, creating only the missing delta.

> **Note**
> The backend key is intentionally `gcp_compute_engie` to match the current Lithops backend module name.

## Installation

Install Google Cloud dependencies:

```bash
python3 -m pip install lithops[gcp]
```

## Required IAM/API setup

Use a service account with permissions to manage Compute Engine resources (instances, networks, subnetworks, firewalls) and enable:

- Compute Engine API (`compute.googleapis.com`)

Optional command:

```bash
gcloud services enable compute.googleapis.com --project <PROJECT_ID>
```

## Create and reuse modes

In `create` mode, Lithops automatically provisions VPC/network resources plus worker VMs during execution and dismantles workers afterward.  
In `reuse` mode, Lithops reuses existing workers and only creates additional workers when needed.

### Configuration

```yaml
lithops:
  backend: gcp_compute_engie
  mode: standalone

gcp:
  credentials_path: <FULL_PATH_TO_SERVICE_ACCOUNT_JSON>

gcp_compute_engie:
  project_name: <GCP_PROJECT_ID>
  zone: <ZONE>            # e.g. us-east1-b
  region: <REGION>        # optional, derived from zone if omitted
  exec_mode: reuse        # create | reuse | consume
  worker_instance_type: e2-standard-2
  master_instance_type: e2-small
```

### Summary of configuration keys (create/reuse)

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_compute_engie|project_name||yes|GCP project ID |
|gcp_compute_engie|zone||yes|Compute Engine zone, for example `us-east1-b` |
|gcp_compute_engie|region|derived from zone|no|Region used for subnet creation |
|gcp_compute_engie|credentials_path||no|Service account JSON path. If omitted, ADC is used |
|gcp_compute_engie|master_instance_type|e2-small|no|Master VM machine type |
|gcp_compute_engie|worker_instance_type|e2-standard-2|no|Worker VM machine type |
|gcp_compute_engie|source_image|ubuntu-2204-lts family|no|Boot image reference |
|gcp_compute_engie|boot_disk_size|50|no|Boot disk size (GB) |
|gcp_compute_engie|boot_disk_type|pd-standard|no|Boot disk type |
|gcp_compute_engie|network_cidr|10.0.0.0/16|no|CIDR for created network |
|gcp_compute_engie|subnet_cidr|10.0.0.0/24|no|CIDR for created subnet |
|gcp_compute_engie|request_spot_instances|False|no|Use Spot VMs for workers |
|gcp_compute_engie|max_workers|100|no|Max number of workers per `FunctionExecutor()` |
|gcp_compute_engie|worker_processes|AUTO|no|Worker process count |
|gcp_compute_engie|exec_mode|reuse|no|One of `consume`, `create`, `reuse` |

## Consume mode

In consume mode, Lithops uses an existing VM and does not provision network/worker resources.

### Configuration

```yaml
lithops:
  backend: gcp_compute_engie
  mode: standalone

gcp:
  credentials_path: <FULL_PATH_TO_SERVICE_ACCOUNT_JSON>

gcp_compute_engie:
  exec_mode: consume
  project_name: <GCP_PROJECT_ID>
  zone: <ZONE>
  instance_name: <EXISTING_VM_NAME>
  ssh_username: ubuntu
  ssh_key_filename: ~/.ssh/id_rsa
```

### Summary of configuration keys (consume)

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|gcp_compute_engie|project_name||yes|GCP project ID |
|gcp_compute_engie|zone||yes|Compute Engine zone |
|gcp_compute_engie|instance_name||yes|Existing VM instance name |
|gcp_compute_engie|ssh_username|ubuntu|no|SSH user for the VM |
|gcp_compute_engie|ssh_key_filename|~/.ssh/id_rsa|no|Path to SSH private key |
|gcp_compute_engie|worker_processes|AUTO|no|Worker process count |

## Test Lithops

```bash
lithops hello -b gcp_compute_engie -s gcp_storage
```

## Viewing execution logs

```bash
lithops logs poll
```
