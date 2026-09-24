# Security policy

## Reporting a vulnerability

Please report security issues **privately** through
[GitHub security advisories](https://github.com/lithops-cloud/lithops/security/advisories/new)
instead of opening a public issue. You will get an acknowledgement within a few working days.

## Security model (read before deploying)

- **The storage bucket must be trusted.** Functions, their arguments, results and statuses
  travel through the Lithops storage bucket as Python pickles (`cloudpickle`). Anyone who can
  write to that bucket (and its `lithops.jobs` / runtime prefixes) can execute code on the
  workers and on the client that reads the results. Restrict write access with bucket
  policies / IAM.
- **Workers run your code with the permissions of the runtime identity** (Lambda execution
  role, Batch job role, Code Engine / Kubernetes service account, VM instance profile). Grant
  least privilege: only the buckets and services your functions need.
- **Credentials live in the Lithops configuration** (`~/.lithops/config`, `.lithops_config`,
  `/etc/lithops/config`, `LITHOPS_CONFIG_FILE` or a config dict) or come from the cloud
  provider's default credential chain. Keep configuration files out of version control and
  readable only by their owner; prefer provider credential chains and short-lived tokens over
  static keys.
- **Standalone mode** opens SSH connections to the VMs it creates and runs a master service
  on them. Keep the security groups / firewall rules Lithops creates restricted to the client,
  and delete idle VMs (`lithops clean`).
- **Runtime images** are built from the Dockerfiles in `runtime/` and the base image you
  choose; keep them patched and pull them only from registries you control.
- Lithops is **not a sandbox**: do not run untrusted functions or data with privileged
  credentials.
