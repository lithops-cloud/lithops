# Swift

Lithops with OpenStack Swift as storage backend.


## Installation

1. Install and configure [Keystone](https://docs.openstack.org/keystone/latest/install/)

2. Install and configure [OpenStack Swift](https://docs.openstack.org/swift/latest/install/)

3. Create a new bucket (container) (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

4. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage: swift

    swift:
        storage_bucket: <BUCKET_NAME>
        auth_url   : <SWIFT_AUTH_URL>
        region     : <SWIFT_REGION>
        user_id    : <SWIFT_USER_ID>
        project_id : <SWIFT_PROJECT_ID>
        password   : <SWIFT_PASSWORD>
        user_domain_name: <SWIFT_USER_DOMAIN>
        project_domain_name: <SWIFT_PROJECT_DOMAIN>
```
 

## Summary of configuration keys for Swift:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|swift | storage_bucket | | yes | The name of a container that exists in you account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in `lithops` section |
|swift | auth_url | |yes | The keystone endpoint for authentication |
|swift | region | |yes | The region of your container |
|swift | project_id | |yes | The Project ID |
|swift | user_id | |yes | The user ID |
|swift | password | |yes | The password |
|swift | user_domain_name | | no | The domain to which the user belongs, by default is set to "default" |
|swift | project_domain_name | | no | The domain associated with the project, by default is set to "default" |
