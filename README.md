
<p align="center"> <img src="docs/images/lithops_flat_cloud_1.png" alt="Lithops"
      width='500' title="Lightweight Optimized Processing"/></p>

Lithops is a multi-cloud distributed computing framework that allows to run unmodified local python code at massive scale on the major of the publicly-available serverless computing platforms. Lithops delivers the user’s code into the cloud without requiring knowledge of how it is deployed and run. Moreover, its multicloud-agnostic architecture ensures portability across cloud providers, overcoming vendor lock-in.

Lithops provides value for a great variety of uses cases: from big data analytics and embarrassingly parallel jobs, that is, highly-parallel programs with little or no need for communication between processes, up to parallel applications that need to share state among processes. Examples of applications that run with Lithops include Monte Carlo simulations, deep learning and machine learning processes, metabolomics computations, and geospatial analytics.


## Quick Start

1. Install Lithops from the PyPi repository:

    ```bash
    $ pip install lithops
    ```

2. Test Lithops by simply running the next command:
  
   ```bash
    $ lithops test
   ```

## Move to the Cloud
Once you have Lithops working in your local machine, you are ready to scale your python code to the cloud. Lithops provides an extensible backend architecture (compute, storage) that is designed to work with different Cloud providers and on-premise backends. Iin this sense, you can code in python and run it unmodified in IBM Cloud, AWS, Azure, Google Cloud and Alibaba Aliyun. Moreover, it also provides support for some kubernetes serverless frameworks such as Knative.

3. [Follow these instructions to configure your compute and storage backends](config/)


<p align="center"> <img src="docs/images/multicloud.png" alt="Lithops"
      width='600' title="Supported Clouds"/></p>


## High-level API

Lithops is shipped with two different high-level APIs.


<table>
<tr>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
<a href="docs/api_futures.md">Futures API</a>
</small>
</p>
</th>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
<a href="docs/api_multiprocessing.md">Multiprocessing API</a>
</small>
</p>
</th>
</tr>

<tr>
<td>

```python
from lithops import FunctionExecutor

def hello(name):
    return 'Hello {}!'.format(name)

with FunctionExecutor() as fexec:
    fut = fexec.call_async(hello, 'World')
    print(fut.result())
```

</td>
<td>

```python
#from multiprocessing import Pool
from lithops.multiprocessing import Pool

def double(i):
    return i * 2

with Pool() as pool:
    result = pool.map(double, [1, 2, 3, 4, 5])
    print(result)
```

</td>
</tr>

</table>

You can find more Lithops usage code examples in the [examples](/examples) folder.

## Execution Modes

Lithops is shipped with 3 different execution modes. The execution mode allows you to decide where the functions are executed.

<table>
<tr>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
<a href="docs/mode_localhost.md">Localhost Mode</a>
</small>
</p>
</th>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
<a href="docs/mode_serverless.md">Serverless Mode</a>
</small>
</p>
</th>
<th align="center">
<img width="441" height="1px">
<p> 
<small>
<a href="docs/mode_standalone.md">Standalone Mode</a>
</small>
</p>
</th>
</tr>
<tr>
<td>

This mode allows to run functions in your local machine, by using processes. This is the default mode of execution if no configuration is provided.

</td>
<td>

This mode allows to run functions by using one or multiple function-as-a-service (FaaS) Serverless compute backends. In this mode of execution, each function invocation equals to a parallel task running in the cloud in an isolated environment.

</td>

<td>

This mode allows to run functions by using a cluster of Virtual machines (VM). In the VMs that conform the cluster, functions run using parallel processes.

</td>
</tr>
</table>

## How to use Lithops

### Functions
[Lithops functions and parameters](docs/functions.md)

### Big Data processing
[Using Lithops to process data from an object store and public URLs](docs/data-processing.md)

### Runtimes 
[Building and managing Lithops runtimes to run the functions](runtime/)

### Notebooks
[Running lithops on Jupyter notebooks](examples/hello_world.ipynb)

## Additional resources

### Blogs
* [Decoding dark molecular matter in spatial metabolomics with IBM Cloud Functions](https://www.ibm.com/cloud/blog/decoding-dark-molecular-matter-in-spatial-metabolomics-with-ibm-cloud-functions)
* [Your easy move to serverless computing and radically simplified data processing](https://www.slideshare.net/gvernik/your-easy-move-to-serverless-computing-and-radically-simplified-data-processing-238929020) Strata Data Conference, NY 2019
  * See video of Lithops usage [here](https://www.youtube.com/watch?v=EYa95KyYEtg&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=3&t=0s) and the example of Monte Carlo [here](https://www.youtube.com/watch?v=vF5HI2q5VKw&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=2&t=0s)
* [Ants, serverless computing, and simplified data processing](https://developer.ibm.com/blogs/2019/01/31/ants-serverless-computing-and-simplified-data-processing/)
* [Speed up data pre-processing with Lithops in deep learning](https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/)
* [Predicting the future with Monte Carlo simulations over IBM Cloud Functions](https://www.ibm.com/cloud/blog/monte-carlo-simulations-with-ibm-cloud-functions)
* [Process large data sets at massive scale with Lithops over IBM Cloud Functions](https://www.ibm.com/cloud/blog/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions)
* [Industrial project in Technion on Lithops](http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/)

### Papers
* [Towards Multicloud Access Transparency in Serverless Computing](https://www.computer.org/csdl/magazine/so/5555/01/09218932/1nMMkpZ8Ko8) - IEEE Software
* [Serverless data analytics in the IBM Cloud](https://dl.acm.org/citation.cfm?id=3284029) - 19th International Middleware Conference


# Acknowledgements

![image](https://user-images.githubusercontent.com/26366936/61350554-d62acf00-a85f-11e9-84b2-36312a35398e.png)

This project has received funding from the European Union's Horizon 2020 research and innovation programme under grant agreement No 825184.
