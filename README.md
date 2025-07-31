<p align="center">
  <a href="http://lithops.cloud">
    <h1 id='lithops' align="center"><img src="docs/_static/lithops_logo_readme.png" alt="Lithops" title="Lightweight Optimized Processing"/></h1>
  </a>
</p>

<p align="center">
  <a aria-label="License" href="https://github.com/lithops-cloud/lithops/blob/master/LICENSE"><img alt="" src="https://img.shields.io/github/license/lithops-cloud/lithops?style=for-the-badge&labelColor=000000"></a>&nbsp<a aria-label="PyPi" href="https://pypi.org/project/lithops/"><img alt="" src="https://img.shields.io/pypi/v/lithops?style=for-the-badge&labelColor=000000"></a>&nbsp<a aria-label="Python" href="#lithops"><img alt="" src="https://img.shields.io/pypi/pyversions/lithops?style=for-the-badge&labelColor=000000"></a>&nbsp<a href="https://pypistats.org/packages/lithops"><img alt="PyPI - Downloads" src="https://img.shields.io/pypi/dm/lithops?label=pypi%7Cdownloads&style=for-the-badge&labelColor=000000"></a>&nbsp<a href="https://deepwiki.com/lithops-cloud/lithops" target="_blank" rel="noopener"><img alt="Ask DeepWiki" src="https://img.shields.io/badge/DeepWiki-Ask%20DeepWiki-blue.svg?style=for-the-badge&labelColor=000000&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACwAAAAyCAYAAAAnWDnqAAAAAXNSR0IArs4c6QAAA05JREFUaEPtmUtyEzEQhtWTQyQLHNak2AB7ZnyXZMEjXMGeK/AIi+QuHrMnbChYY7MIh8g01fJoopFb0uhhEqqcbWTp06/uv1saEDv4O3n3dV60RfP947Mm9/SQc0ICFQgzfc4CYZoTPAswgSJCCUJUnAAoRHOAUOcATwbmVLWdGoH//PB8mnKqScAhsD0kYP3j/Yt5LPQe2KvcXmGvRHcDnpxfL2zOYJ1mFwrryWTz0advv1Ut4CJgf5uhDuDj5eUcAUoahrdY/56ebRWeraTjMt/00Sh3UDtjgHtQNHwcRGOC98BJEAEymycmYcWwOprTgcB6VZ5JK5TAJ+fXGLBm3FDAmn6oPPjR4rKCAoJCal2eAiQp2x0vxTPB3ALO2CRkwmDy5WohzBDwSEFKRwPbknEggCPB/imwrycgxX2NzoMCHhPkDwqYMr9tRcP5qNrMZHkVnOjRMWwLCcr8ohBVb1OMjxLwGCvjTikrsBOiA6fNyCrm8V1rP93iVPpwaE+gO0SsWmPiXB+jikdf6SizrT5qKasx5j8ABbHpFTx+vFXp9EnYQmLx02h1QTTrl6eDqxLnGjporxl3NL3agEvXdT0WmEost648sQOYAeJS9Q7bfUVoMGnjo4AZdUMQku50McDcMWcBPvr0SzbTAFDfvJqwLzgxwATnCgnp4wDl6Aa+Ax283gghmj+vj7feE2KBBRMW3FzOpLOADl0Isb5587h/U4gGvkt5v60Z1VLG8BhYjbzRwyQZemwAd6cCR5/XFWLYZRIMpX39AR0tjaGGiGzLVyhse5C9RKC6ai42ppWPKiBagOvaYk8lO7DajerabOZP46Lby5wKjw1HCRx7p9sVMOWGzb/vA1hwiWc6jm3MvQDTogQkiqIhJV0nBQBTU+3okKCFDy9WwferkHjtxib7t3xIUQtHxnIwtx4mpg26/HfwVNVDb4oI9RHmx5WGelRVlrtiw43zboCLaxv46AZeB3IlTkwouebTr1y2NjSpHz68WNFjHvupy3q8TFn3Hos2IAk4Ju5dCo8B3wP7VPr/FGaKiG+T+v+TQqIrOqMTL1VdWV1DdmcbO8KXBz6esmYWYKPwDL5b5FA1a0hwapHiom0r/cKaoqr+27/XcrS5UwSMbQAAAABJRU5ErkJggg==" style="vertical-align:middle;"></a>
</p>

Lithops is a Python multi-cloud distributed computing framework that lets you run unmodified Python code at massive scale across cloud, HPC, and on-premise platforms. It supports major cloud providers and Kubernetes platforms, running your code transparently without requiring you to manage deployment or infrastructure.

Lithops is ideal for highly parallel workloads—such as Monte Carlo simulations, machine learning, metabolomics, or geospatial analytics—and lets you tailor execution to your priorities: you can optimize for performance using AWS Lambda to launch hundreds of functions in milliseconds, or reduce costs by running the same code on AWS Batch with Spot Instances.

## Installation

1. Install Lithops from the PyPi repository:

    ```bash
    pip install lithops
    ```

2. Execute a *Hello World* function:
  
   ```bash
   lithops hello
   ```

## Configuration
Lithops provides an extensible backend architecture (compute, storage) designed to work with various cloud providers and on-premise platforms. You can write your code in Python and run it unmodified across major cloud providers and Kubernetes environments.

[Follow these instructions to configure your compute and storage backends](config/)

<p align="center">
<a href="config/README.md#compute-and-storage-backends">
<img src="docs/source/images/multicloud.jpg" alt="Multicloud Lithops" title="Multicloud Lithops"/>
</a>
</p>


## High-level API

Lithops is shipped with 2 different high-level Compute APIs, and 2 high-level Storage APIs

<div align="center">
<table>
<tr>
  <th>
    <img width="50%" height="1px">
    <p><small><a href="docs/api_futures.md">Futures API</a></small></p>
  </th>
  <th>
    <img width="50%" height="1px">
    <p><small><a href="docs/source/api_multiprocessing.rst">Multiprocessing API</a></small></p>
  </th>
</tr>

<tr>
<td>

```python
from lithops import FunctionExecutor

def double(i):
    return i * 2

with FunctionExecutor() as fexec:
    f = fexec.map(double, [1, 2, 3, 4])
    print(f.result())
```
</td>
<td>

```python
from lithops.multiprocessing import Pool

def double(i):
    return i * 2

with Pool() as pool:
    result = pool.map(double, [1, 2, 3, 4])
    print(result)
```
</td>
</tr>

</table>

<table>
<tr>
  <th>
    <img width="50%" height="1px">
    <p><small><a href="docs/api_storage.md">Storage API</a></small></p>
  </th>
  <th>
    <img width="50%" height="1px">
    <p><small><a href="docs/source/api_storage_os.rst">Storage OS API</a></small></p>
  </th>
</tr>

<tr>
<td>

```python
from lithops import Storage

if __name__ == "__main__":
    st = Storage()
    st.put_object(bucket='mybucket',
                  key='test.txt',
                  body='Hello World')

    print(st.get_object(bucket='lithops',
                        key='test.txt'))
```
</td>
<td>

```python
from lithops.storage.cloud_proxy import os

if __name__ == "__main__":
    filepath = 'bar/foo.txt'
    with os.open(filepath, 'w') as f:
        f.write('Hello world!')

    dirname = os.path.dirname(filepath)
    print(os.listdir(dirname))
    os.remove(filepath)
```
</td>
</tr>

</table>
</div>

You can find more usage examples in the [examples](/examples) folder.

## Documentation

For documentation on using Lithops, see [latest release documentation](https://lithops-cloud.github.io/docs/)

If you are interested in contributing, see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Additional resources

### Blogs and Talks

* [How to run Lithops over EC2 VMs using the new K8s backend](https://danielalecoll.medium.com/how-to-run-lithops-over-ec2-vms-using-the-new-k8s-backend-4b0a4377c4e9) 
* [Simplify the developer experience with OpenShift for Big Data processing by using Lithops framework](https://medium.com/@gvernik/simplify-the-developer-experience-with-openshift-for-big-data-processing-by-using-lithops-framework-d62a795b5e1c)
* [Speed-up your Python applications using Lithops and Serverless Cloud resources](https://itnext.io/speed-up-your-python-applications-using-lithops-and-serverless-cloud-resources-a64beb008bb5)
* [Lithops, a Multi-cloud Serverless Programming Framework](https://itnext.io/lithops-a-multi-cloud-serverless-programming-framework-fd97f0d5e9e4)
* [CNCF Webinar - Toward Hybrid Cloud Serverless Transparency with Lithops Framework](https://www.youtube.com/watch?v=-uS-wi8CxBo)
* [Your easy move to serverless computing and radically simplified data processing](https://www.slideshare.net/gvernik/your-easy-move-to-serverless-computing-and-radically-simplified-data-processing-238929020) Strata Data Conference, NY 2019. See video of Lithops usage [here](https://www.youtube.com/watch?v=EYa95KyYEtg&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=3&t=0s) and the example of Monte Carlo [here](https://www.youtube.com/watch?v=vF5HI2q5VKw&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=2&t=0s)

<!---
* [Serverless Without Constraints](https://www.ibm.com/cloud/blog/serverless-without-constraints)
* [Using Serverless to Run Your Python Code on 1000 Cores by Changing Two Lines of Code](https://www.ibm.com/cloud/blog/using-serverless-to-run-your-python-code-on-1000-cores-by-changing-two-lines-of-code)
* [Decoding dark molecular matter in spatial metabolomics with IBM Cloud Functions](https://www.ibm.com/cloud/blog/decoding-dark-molecular-matter-in-spatial-metabolomics-with-ibm-cloud-functions)
* [Speed up data pre-processing with Lithops in deep learning](https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/)
* [Predicting the future with Monte Carlo simulations over IBM Cloud Functions](https://www.ibm.com/cloud/blog/monte-carlo-simulations-with-ibm-cloud-functions)
* [Process large data sets at massive scale with Lithops over IBM Cloud Functions](https://www.ibm.com/cloud/blog/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions)
* [Industrial project in Technion on Lithops](http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/)
-->

### Papers
* [Serverful Functions: Leveraging Servers in Complex Serverless Workflows](https://dl.acm.org/doi/10.1145/3700824.3701095)  - ACM Middleware Industrial Track 2024 
* [Transparent serverless execution of Python multiprocessing applications](https://dl.acm.org/doi/10.1016/j.future.2022.10.038) - Elsevier Future Generation Computer Systems 2023
* [Outsourcing Data Processing Jobs with Lithops](https://ieeexplore.ieee.org/document/9619947) - IEEE Transactions on Cloud Computing 2022
* [Towards Multicloud Access Transparency in Serverless Computing](https://www.computer.org/csdl/magazine/so/5555/01/09218932/1nMMkpZ8Ko8) - IEEE Software 2021
* [Primula: a Practical Shuffle/Sort Operator for Serverless Computing](https://dl.acm.org/doi/10.1145/3429357.3430522) - ACM/IFIP International Middleware Conference 2020. [See presentation here](https://www.youtube.com/watch?v=v698iu5YfWM)
* [Bringing scaling transparency to Proteomics applications with serverless computing](https://dl.acm.org/doi/abs/10.1145/3429880.3430101) - 6th International Workshop on Serverless Computing (WoSC6) 2020. [See presentation here](https://www.serverlesscomputing.org/wosc6/#p10)
* [Serverless data analytics in the IBM Cloud](https://dl.acm.org/citation.cfm?id=3284029) - ACM/IFIP International Middleware Conference 2018


# Acknowledgements
This project has received funding from the European Union's Horizon 2020 research and innovation programme under grant agreement No 825184 (CloudButton).
