# Lithops runtime for Singularity
This document describes how to use Singularity containers as runtimes for your Lithops functions.

The runtime provides a pre-configured environment to execute your Lithops functions within Singularity containers. It includes the necessary and dependencies to execute your lithops code. 

**Note:** This backend requires a RabbitMQ server for communication.

## Building a Singularity Runtime

Use the `lithops runtime build` command to create a `.sif` image containing the necessary Lithops environment.

1. **Building a basic runtime**

        $ lithops runtime build -b singularity singularity-runtime-name --fakeroot --force

    This command creates the a new `singularity-runtime-name.sif` file with the necessary libraries.


2. **Building a custom runtime from a definition file**

    For greater control and flexibility with custom packages, use a Singularity definition file (.def):

        $ lithops runtime build -b singularity my-custom-runtime -f my-runtime.def --fakeroot --force

    This command generates `my-custom-runtime.sif` based on `my-runtime.def`.


**Building flags:**
* `--fakeroot`: Often required for building Singularity images without root privileges.
* `--force`: Overwrites any existing images with the same name.

You can find more information about the Singularity flags in the [Singularity documentation](https://docs.sylabs.io/guides/latest/user-guide/build_a_container.html).


## Deploying and Running the Runtime

We need to perform a manual deployment because we do not have direct access to the cluster nodes. In this case, manually transferring the built `.sif` image to each cluster node is necessary. This ensures that the required runtime environment is available on each node for running Lithops functions.

1. **Image Transfer:** Manually transfer the built `.sif` image to each cluster node that will run Lithops functions.

2. **Starting the Singularity Instance:** On each node, start a Singularity instance with your runtime image:

        $ singularity instance start --fakeroot /tmp/singularity-runtime-name.sif lithops-worker

    This creates a Singularity instance called `lithops-worker`.

3. **Running Functions:** Execute Lithops functions within this instance:

        $ singularity run --env AMQP_URL=amqp://<username>:<password>@<rabbitmq_host>:<rabbitmq_port>/<vhost> instance://lithops-worker

    Replace the placeholders (e.g., `<username>`) with your RabbitMQ credentials to enable communication between your Lithops client and the function runtime.

## Configuration
By default, the Singularity runtime uses the `/tmp` directory to store the `.sif` images. You can customize this path in your Lithops configuration file:

```yaml
singularity:
    sif_path: /your/custom/path
    runtime: singularity-runtime-name
```

Also, to execute the Singularity backend, you need to set the RabbitMQ AMPQ URL in your configuration file:

```yaml
rabbitmq:
    amqp_url: amqp://<username>:<password>@<rabbitmq_host>:<rabbitmq_port>/<vhost>
```