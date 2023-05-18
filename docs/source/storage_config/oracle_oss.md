# Oracle Object Storage

Lithops with Oracle Object Storage as storage backend.

## Installation

1. Install Oracle Cloud backend dependencies:

## Configuration

1. Navigate to the [Oracle Cloud Console](https://console.oraclecloud.com/) and create a new API signing keys (If you don't have one)

2. Edit your Lithops config and add the following keys:

```yaml
lithops:
    storage : oracle_oss

oracle:
    storage_bucket : <STORAGE_BUCKET>
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

