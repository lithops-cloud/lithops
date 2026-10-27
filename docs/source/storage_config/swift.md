# Swift

Lithops with OpenStack Swift as storage backend.


## Installation

1. Install and configure [Keystone](https://docs.openstack.org/keystone/latest/install/)

2. Install and configure [OpenStack Swift](https://docs.openstack.org/swift/latest/install/)

3. Create a new bucket (container) (e.g. `lithops-data`). Remember to update the corresponding Lithops config field with this bucket name.

## Configuration

1. Edit your Lithops config file and add the following keys:

```yaml
    lithops:
        storage: swift

    swift:
        storage_bucket: <BUCKET_NAME>
        auth_url: <SWIFT_AUTH_URL>
        region: <SWIFT_REGION>
        user_name: <USER_NAME>
        project_name: <PROJECT_NAME>
        password: <SWIFT_PASSWORD>
        user_domain_name: Default
        project_domain_name: Default
```

`user_id` and `project_id` identify the user and the project by id instead of by name. Set one of each pair. `auth_url` may or may not end in `/v3`. `endpoint` replaces the storage URL published in the Keystone catalog.

## Summary of configuration keys for Swift:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|swift | storage_bucket | | yes | The name of a container that exists in your account. This will be used by Lithops for intermediate data. If set, this will overwrite the `storage_bucket` set in the `lithops` section |
|swift | auth_url | | yes | The Keystone endpoint. A trailing `/v3` is optional |
|swift | region | | yes | The region of the public Swift endpoint in the catalog |
|swift | user_name | | no | The user name. Required unless `user_id` is set |
|swift | user_id | | no | The user id. A value that is not an id is used as the user name |
|swift | project_name | | no | The project name. Required unless `project_id` is set |
|swift | project_id | | no | The project id. A value that is not an id is used as the project name |
|swift | password | | yes | The password |
|swift | user_domain_name | Default | no | The domain of a user named with `user_name` |
|swift | project_domain_name | Default | no | The domain of a project named with `project_name` |
|swift | endpoint | | no | Storage URL. Replaces the public URL from the Keystone catalog |
