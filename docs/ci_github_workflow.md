# Continuous Integration Github Workflow

Lithops contains a Continuous Integration (CI) github workflow that can run manually or automatically on each PR.
Currently, it runs the tests using the IBM Code Engine, IBM Cloud Functions and Localhost backends.

To make it working with IBM Code Engine and IBM Cloud Functions, you must set in your Lithops repo some access secretes.
Navigate to your lithops (fork) repo >> Settings >> secrets (on the left menu)

- Both IBM Code engine and IBM Cloud Functions builds a docker runtime to run the tests. So you must have a docker hub account and its credentials on github. To Configure **Docker**, create a new secret named **DOCKER_USER**, and add your *username*. Then create a new secret named **DOCKER_TOKEN**, and add your *token*. 

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
