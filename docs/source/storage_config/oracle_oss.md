# Oracle Object Storage

Lithops with Oracle Object Storage as storage backend.

**Note**: This is a beta backend. Please open an issue if you encounter any error/bug

## Installation

1. Install Oracle Cloud backend dependencies:

```bash
python3 -m pip install lithops[oracle]
```

## Configuration

1. Navigate to the [API keys page](https://cloud.oracle.com/identity/domains/my-profile/api-keys) and generate and download a new API signing keys. Omit this step if you already generated and downloaded one key. When you generate a new Key, oracle provides a sample config file with most of the required parameters by lithops. Copy all the `key:value` pairs and configure lithops as follows:

```yaml
lithops:
    storage : oracle_oss

oracle:
    user: <USER>
    region: <REGION>
    fingerprint: <FINGERPRINT>
    tenancy: <TENANCY>
    key_file: <KEY_FILE>
    compartment_id: <COMPARTMENT_ID>
```

## Summary of configuration keys for Oracle:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle | user | |yes |  Oracle Cloud User's OCID from [here](https://cloud.oracle.com/identity/domains/my-profile) |
|oracle | region | |yes | Region Identifier from [here](https://cloud.oracle.com/regions). For example: `eu-madrid-1` |
|oracle | fingerprint | |yes | Fingerprint of the private key PEM file from [here](https://cloud.oracle.com/identity/domains/my-profile/api-keys)|
|oracle | tenancy | |yes | Tenancy's OCID from [here](https://cloud.oracle.com/tenancy)|
|oracle | key_file | |yes | Path to the private key (PEM) file |
|oracle | compartment_id | |yes | Compartment's ID from [here](https://cloud.oracle.com/identity/compartments)|
|oracle | tenancy_namespace | |no | Auto-generated Object Storage namespace string of the tenancy. You cand find it [here](https://cloud.oracle.com/tenancy), under *Object storage namespace*|

## Summary of configuration keys for Oracle Object Storage Service :

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_oss | region | |no | Region name. For example: `eu-madrid-1`. Lithops will use the region set under the `oracle` section if it is not set here  |
|oracle_oss | storage_bucket | |no | The name of a bucket that exists in your account. Lithops will automatically create a new bucket if it is not provided|
