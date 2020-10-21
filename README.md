
<p align="center"> <img src="docs/images/lithops_flat_cloud_2.png" alt="Lithops"
      width='500' title="Lightweigt Optimised Processing"/></p>


Lithops framework is a rebranded [PyWren-IBM](https://dl.acm.org/citation.cfm?id=3284029) framework. Lithops goals are massively scaling the execution of Python code and its dependencies on serverless computing platforms and monitoring the results. Lithops delivers the user’s code into the serverless platform without requiring knowledge of how functions are invoked and run.

Lithops provides great value for the variety of uses cases, like processing data in object storage, running embarrassingly parallel compute jobs (e.g. Monte-Carlo simulations), enriching data with additional attributes and many more. In extending Lithops to work with object storage, we also added a partition discovery component that allows Lithops to process large amounts of data stored in the object storage. See [changelog](CHANGELOG.md) for more details.

### Lithops and IBM Cloud 
Lithops is officially supported for IBM Cloud and Red Hat OpenShift. Students or academic stuff are welcome to follow [IBM Academic Initiative](https://ibm.biz/academic), a special program that allows free trial of IBM Cloud for Academic institutions. This program is provided for students and faculty staff members, and allow up to 12 months of free usage. You can register your university email and get a free of charge account.

### Lithops Multi-cloud
Lithops provides an extensible backend architecture (compute, storage) that is designed to work with different Cloud providers and on-premise backends (Knative, OpenWhisk). You can code in Lithops and run it unmodified in IBM Cloud, AWS, Azure, Google Cloud and Alibaba Aliyun.


## Quick Start

1. Install Lithops from the PyPi repository:

    ```bash
    $ pip install lithops
    ```

2. [Follow these instructions to configure your compute and storage backends](config/)

3. Test Lithops by simply running the next command:
  
   ```bash
    $ lithops test
   ```

   or by running the next code:

   ```python
   import lithops

   def hello(name):
       return 'Hello {}!'.format(name)

   fexec = lithops.FunctionExecutor()
   fexec.call_async(hello, 'World')
   print(fexec.get_result())
   ```

## Additional information and examples


* **Examples**: You can find various examples in [examples](/examples) folder
* **Lithops API and Exectors**: [Lithops API and Executors](docs/api-details.md)
* **Functions**: [Lithops functions and parameters](docs/functions.md)
* **Runtimes**: [Building and managing Lithops runtimes to run the functions](runtime/)
* **Data processing**: [Using Lithops to process data from IBM Cloud Object Storage and public URLs](docs/data-processing.md)
* **Notebooks**: [Lithops on IBM Watson Studio and Jupyter notebooks](examples/hello_world.ipynb)

## How to contribute code
Follow guidance [how to contribute](docs/how-to-contribute.md) code to the project

## Additional resources

* [Decoding dark molecular matter in spatial metabolomics with IBM Cloud Functions](https://www.ibm.com/cloud/blog/decoding-dark-molecular-matter-in-spatial-metabolomics-with-ibm-cloud-functions)
* [Your easy move to serverless computing and radically simplified data processing](https://www.slideshare.net/gvernik/your-easy-move-to-serverless-computing-and-radically-simplified-data-processing-238929020) Strata Data Conference, NY 2019
  * See video of Lithops usage [here](https://www.youtube.com/watch?v=EYa95KyYEtg&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=3&t=0s) and the example of Monte Carlo [here](https://www.youtube.com/watch?v=vF5HI2q5VKw&list=PLpR7f3Www9KCjYisaG7AMaR0C2GqLUh2G&index=2&t=0s)
* [Ants, serverless computing, and simplified data processing](https://developer.ibm.com/blogs/2019/01/31/ants-serverless-computing-and-simplified-data-processing/)
* [Speed up data pre-processing with Lithops in deep learning](https://developer.ibm.com/patterns/speed-up-data-pre-processing-with-pywren-in-deep-learning/)
* [Predicting the future with Monte Carlo simulations over IBM Cloud Functions](https://www.ibm.com/cloud/blog/monte-carlo-simulations-with-ibm-cloud-functions)
* [Process large data sets at massive scale with Lithops over IBM Cloud Functions](https://www.ibm.com/cloud/blog/process-large-data-sets-massive-scale-pywren-ibm-cloud-functions)
* [Industrial project in Technion on Lithops](http://www.cs.technion.ac.il/~cs234313/projects_sites/W19/04/site/)
* [Serverless data analytics in the IBM Cloud](https://dl.acm.org/citation.cfm?id=3284029) - Proceedings of the 19th International Middleware Conference (Industry)

# Acknowledgements

![image](https://user-images.githubusercontent.com/26366936/61350554-d62acf00-a85f-11e9-84b2-36312a35398e.png)

This project has received funding from the European Union's Horizon 2020 research and innovation programme under grant agreement No 825184.
