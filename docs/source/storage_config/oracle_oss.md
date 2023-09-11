# Oracle Object Storage (beta)

Lithops with Oracle Object Storage as storage backend.

**Note**: This is a beta backend. Please open an issue if you encounter any error/bug

## Installation

1. Install Oracle Cloud backend dependencies:

## Configuration

1. Navigate to the [Oracle Cloud Console](https://console.oraclecloud.com/) and create a new API signing keys (If you don't have one)

2. Edit your Lithops config and add the following keys:

```yaml
lithops:
    storage : oracle_oss

oracle:
    user : <USER>
    key_file : <KEY_FILE>
    fingerprint : <FINGERPRINT>
    tenancy : <TENANCY>
    region : <REGION>
    compartment_id: <COMPARTMENT_ID>
    namespace_name : <NAMESPACE_NAME>

oracle_oss:
    storage_bucket : <STORAGE_BUCKET>
```

## Summary of configuration keys for Oracle:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle | user | |yes |  Oracle Cloud User's OCID |
|oracle | key_file | |yes | Path to the PEM file |
|oracle | fingerprint | |yes | Fingerprint of the PEM file |
|oracle | tenancy | |yes | Tenancy's OCID |
|oracle | region | |yes | Region name. For example: `eu-madrid-1` |
|oracle | compartment_id | |yes | Compartment's OCID |
|oracle | namespace_name | |yes | Namespace name for the container registry where docker images are uploaded |

## Summary of configuration keys for Oracle Object Storage Service :

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_oss | storage_bucket | |yes | Bucket name. For example: `oracle-bucket`|
