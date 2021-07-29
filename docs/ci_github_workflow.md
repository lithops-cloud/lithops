# Continuous Integration Github Workflow

Lithops contains a Continuous Integration (CI) github workflow that can run manually or automatically on each PR.
Currently, it runs the tests using the IBM Code Engine, IBM Cloud Functions and Localhost backends.

To make it work with IBM Code Engine and IBM Cloud Functions, you must set in your Lithops repo some access secretes.
Navigate to your lithops repo >> Settings >> secrets (on the left menu)

- Both IBM Code engine and IBM Cloud Functions builds a docker runtime to run the tests. So you must have a docker hub account and set its credentials on github. To Configure **Docker**, create a new secret named **DOCKER_USER**, and add your *username*. Then create a new secret named **DOCKER_TOKEN**, and add your *token*. 

- To Configure **IBM Cloud Functions** and **IBM Code Engine**, create a new secret named **LITHOPS_CONFIG**, and add the following content with your information:

```yaml
code_engine:
    namespace: <>
    region: <>
    iam_api_key: <>
    # Do not modify runtime entry
    runtime: lithops-ce

ibm_cf:
    endpoint: <>
    namespace: <>
    api_key: <>
    # Do not modify runtime entry
    runtime: lithops-cf

ibm_cos:
    storage_bucket: <>
    region: <>
    api_key: <>
```

Note that this example is only a minimum configuration. **LITHOPS_CONFIG** secret is in fact a [lithops config file](./config/config_template.yaml), so you can set the same keys as the ones described in [config/](../config) and in its backends. 

- Alternatively, you can only provide one of the **IBM Cloud Functions** or **IBM Code Engine** configs in the **LITHOPS_CONFIG** secret. In this case, only the configured backend will run the tests. For example, if we only configure **IBM Cloud Functions**, **IBM Code Engine** tests will be skipped, but the whole workflow will be successful if **IBM Cloud Functions** tests are successful.

```yaml
ibm_cf:
    endpoint: <>
    namespace: <>
    api_key: <>
    # Do not modify runtime entry
    runtime: lithops-cf

ibm_cos:
    storage_bucket: <>
    region: <>
    api_key: <>
```
