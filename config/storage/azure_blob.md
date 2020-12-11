# Lithopsa on Microsoft Azure

Lithops with Azure Blob Storage as storage backend.


### Configuration

1. Install Microsoft Azure backend dependencies:

```
$ pip install lithops[azure]
```

2. Edit your lithops config and add the following keys:

```yaml
  lithops:
    storage : azure_blob

  azure_blob:
    storage_account : <STORAGE_ACCOUNT_NAME>
    storage_account_key : <STORAGE_ACCOUNT_KEY>
```
   - `account_name`: the name of the Storage Account itself.
   - `account_key`: an Account Key, found in *Storage Account* > `account_name` > *Settings* > *Access Keys*.
