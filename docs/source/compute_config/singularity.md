# Singularity

Lithops with *Singularity* as a serverless compute backend is **ideal for High-Performance Computing (HPC) environments** where Docker might be restricted due to security concerns or administrative privileges. Singularity's ability to run containers without requiring root access makes it a suitable choice for such environments. 

**Note:** This backend requires a RabbitMQ server for communication and coordination between Lithops components.

## Configuration

### Configure RabbiMQ

   ```yaml
   lithops:
       backend: singularity
       monitoring: rabbitmq

   rabbitmq:
       amqp_url: amqp://<username>:<password>@<rabbitmq_host>:<rabbitmq_port>/<vhost> 
   ```

   Replace `<username>`, `<password>`, `<rabbitmq_host>`, `<rabbitmq_port>`, and `<vhost>` with your RabbitMQ credentials. 

### Configure Singularity backend

   ```yaml
   singularity:
       worker_processes: <WORKER_PROCESSES>
       runtime: <RUNTIME_NAME>
       sif_path: <CUSTOM_PATH>
   ```

## Summary of Configuration Keys for Singularity

| Group       | Key                 | Default | Mandatory | Additional info                                                                                                                                               |
|-------------|----------------------|---------|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| singularity | worker_processes    |  1  | no       | Number of functions sent in each RabbitMQ package. Ideally, set to a multiple of the node's CPU count.                       |
| singularity | runtime              |    | yes       | Name of the Singularity runtime image (`.sif`) file containing the Lithops runtime environment.                                                                    |
| singularity | sif_path            |  /tmp  | no       | Directory path where the Singularity runtime image  `.sif` will be stored.                                                                       |

## Deploying the Runtime Image

Since Lithops doesn't directly manage Singularity instances on your cluster, you need to ensure the runtime image is available on **each** node:

1. **Transfer:** Manually copy the built `.sif` runtime image to each node in your cluster. 

2. **Start:**  Start a new Singularity instance on each node using the `.sif` file. Then run the instance and add the RabbitMQ server details to the environment variables. 

   ```bash
   singularity instance start --fakeroot /path/to/sif/your-singularity-runtime.sif <INSTANCE_NAME>
   singularity run instance://<INSTANCE_NAME> --env AMQP_URL=amqp://<username>:<password>@<rabbitmq_host>:<rabbitmq_port>/<vhost>
   ```

Depending on your cluster setup, you might need to adjust permissions of the `.sif` file or the [singularity flags](https://docs.sylabs.io/guides/latest/user-guide/cli/singularity_exec.html#singularity-exec) to ensure that the user running the Lithops worker can access and execute it. 


## Test Lithops
Once you have your compute and storage backends configured, you can run a hello world function with:

```bash
lithops hello -b singularity
```

## Viewing the execution logs

You can view the function executions logs in your local machine using the *lithops client*:

```bash
lithops logs poll
```
