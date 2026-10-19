# OpenWhisk

Lithops with *OpenWhisk* as serverless compute backend. Lithops can also run functions on vanilla OpenWhisk installations, for example by deploying OpenWhisk with [openwhisk-devtools](https://github.com/apache/openwhisk-devtools).


## Installation

1. Install the [openwhisk-cli](https://github.com/apache/openwhisk-cli).


2. Make sure you can run an end-to-end [Python example](https://github.com/apache/openwhisk/blob/master/docs/actions-python.md#creating-and-invoking-python-actions).

    For example, create a file named `hello.py` with the next content:
    
    ```python
    def main(args):
        name = args.get("name", "stranger")
        greeting = "Hello " + name + "!"
        print(greeting)
        return {"greeting": greeting}
    ```
    
    Now issue the `wsk` command to deploy the python action:
    
    ```
    wsk action create helloPython hello.py
    ```
    
    Finally, test the helloPython action:
    
    ```
    wsk action invoke --result helloPython --param name World
    ```

## Local OpenWhisk

The current standalone build is published on Docker Hub as `openwhisk/standalone:nightly` (the same image as the `7ef091c` tag). It serves the API over plain HTTP, so the endpoint keeps the `http://` scheme:

```bash
docker run -d --name openwhisk -h openwhisk \
  -e DOCKER_API_VERSION=1.40 \
  -p 3233:3233 -p 3232:3232 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  openwhisk/standalone:nightly
```

The image carries Docker 18.06 to launch action containers. `DOCKER_API_VERSION=1.40` lets that client talk to a current Docker daemon, which otherwise rejects it. Its Python runtimes are `python:3.10` and `python:3.11`, and an action is limited to 128–512 MB and 300 seconds.

The playground is at <http://localhost:3232>. The guest namespace and its key are printed at startup (`docker logs openwhisk | grep 'wsk property'`) and are, by default:

```yaml
openwhisk:
    endpoint    : http://localhost:3233
    namespace   : guest
    api_key     : 23bc46b1-71f6-4ed5-8c54-816aa4f8c502:123zO3xZCLrMN6v2BKK1dXYFpXlPkccOFqm12CdAsMgRU4VrNZ9lyGVCGuMDGIwP
```

Shut it down with `docker exec openwhisk stop`, which also removes the action containers it started.

## Configuration

3. Edit your Lithops config and add the following keys:

   ```yaml
    lithops:
        backend: openwhisk

    openwhisk:
        endpoint    : <OW_ENDPOINT>
        namespace   : <NAMESPACE>
        api_key     : <AUTH_KEY>
        insecure    : <True/False>
    ```

    - You can find all the values in the `~/.wskprops` file. The content of the file should look like:

        ```
        APIHOST=192.168.1.30
        AUTH=23bc46b1-71f6-4ed5-8c54-816aa4f8c50:123zO3xZCLrMN6v2BKK1dXYFpXlPkccOFqm12CdAsMgRU4VrNZ9lyGVCG
        INSECURE_SSL=true
        NAMESPACE=guest
        ```
        
        Copy all the values into the lithops config file as:
        
        ```yaml
        openwhisk:
            endpoint    : https://192.168.1.30
            namespace   : guest
            api_key     : 23bc46b1-71f6-4ed5-8c54-816aa4f8c50:123zO3xZCLrMN6v2BKK1dXYFpXlPkccOFqm12CdAsMgRU4VrNZ9lyGVCG
            insecure    : True
        ```

## Summary of configuration keys for Openwhisk:

|Group|Key|Default|Mandatory|Additional info|
|---|---|---|---|---|
|openwhisk | endpoint | |yes | API Host endpoint |
|openwhisk | namespace | |yes | Namespace |
|openwhisk | api_key | |yes | API Auth|
|openwhisk | insecure | False |no | Skip TLS verification. Leave false for an `http://` endpoint |
|openwhisk | max_workers | 100 | no | Max number of workers per `FunctionExecutor()`. Keep it within the concurrent invocations the namespace allows: the invocations over that limit are rejected and retried |
|openwhisk | worker_processes | 1 | no | Number of Lithops processes within a given worker. This can be used to parallelize function activations within a worker |
|openwhisk | runtime |  |no | Docker image name |
|openwhisk | runtime_memory | 256 |no | Memory limit in MB. Default 256MB |
|openwhisk | runtime_timeout | 300 |no | Runtime timeout in seconds. Default 5 minutes |
|openwhisk | invoke_pool_threads | 100 |no | Number of concurrent threads used for invocation |
|openwhisk | runtime_include_function | False | no | If set to true, Lithops will automatically build a new runtime, including the function's code, instead of transferring it through the storage backend at invocation time. This is useful when the function's code size is large (on the order of tens of MB) and the code does not change frequently |

## Test Lithops

Once you have your compute and storage backends configured, you can run a Hello World function with:

```bash
lithops hello -b openwhisk -s ibm_cos
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```