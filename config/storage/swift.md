# Lithops on OpenStack Swift

Lithops with OpenStack Swift as storage backend.


### Installation

1. Install and configure [Keystone](https://docs.openstack.org/keystone/latest/install/)

2. Install and configure [OpenStack Swift](https://docs.openstack.org/swift/latest/install/)


### Configuration

3. Edit your lithops config file and add the following keys:

```yaml
    lithops:
        storage_backend: swift

    swift:
        auth_url   : <SWIFT_AUTH_URL>
        region     : <SWIFT_REGION>
        user_id    : <SWIFT_USER_ID>
        project_id : <SWIFT_PROJECT_ID>
        password   : <SWIFT_PASSWORD>
```

- `auth_url`: The keystone endpoint for authenthication.
- `region`: The region of your container
- `user_id`: The user ID
- `project_id`: The Project ID
- `password`: The password
 
