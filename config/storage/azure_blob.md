# Lithops on Microsoft Azure

Lithops with Azure Blob Storage as storage backend.


### Configuration

1. Install Microsoft Azure backend dependencies:

```
$ python3 -m pip install lithops[azure]
```

2. Navigate to your storage account and create a new bucket (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

3. Edit your lithops config and add the following keys:

```yaml
  lithops:
      storage : azure_blob
      storage_bucket: <BUCKET_NAME>

  azure_blob:
      storage_account : <STORAGE_ACCOUNT_NAME>
      storage_account_key : <STORAGE_ACCOUNT_KEY>
```
   - `account_name`: the name of the Storage Account itself.
   - `account_key`: an Account Key, found in *Storage Account* > `account_name` > *Settings* > *Access Keys*.
