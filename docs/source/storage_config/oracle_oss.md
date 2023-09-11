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

## Summary of configuration keys for Oracle Object Storage Service :

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|oracle_oss | region | |no | Region name. For example: `eu-madrid-1`. Lithops will use the region set under the `oracle` section if it is not set here  |
|oracle_oss | storage_bucket | |no | The name of a bucket that exists in your account. Lithops will automatically create a new bucket if it is not provided|
