# Example of Docker image that is based on anaconda image (Python 3.6)
# This image also includes PyWren requirements and needed dependencies
# so it can be used as a base image for IBM Cloud Functions

FROM continuumio/miniconda3:4.5.4

ENV FLASK_PROXY_PORT 8080

RUN apt-get update && apt-get install -y \
        gcc \
        libc-dev \
        libxslt-dev \
        libxml2-dev \
        libffi-dev \
        libssl-dev \
        zip \
        unzip \
        vim \
        && rm -rf /var/lib/apt/lists/*

RUN apt-cache search linux-headers-generic

# Add your Conda required packages here. Ensure "conda clean --all" at 
# the end to remove temporary data. One "RUN" line is better than multiple
# ones in terms of image size. For example:
#RUN conda install -c conda-forge opencv && conda install sortedcontainers gevent-websocket && conda clean --all

COPY requirements.txt requirements.txt

RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt

# create action working directory
RUN mkdir -p /action

RUN mkdir -p /actionProxy
ADD https://raw.githubusercontent.com/apache/incubator-openwhisk-runtime-docker/8b2e205c39d84ed5ede6b1b08cccf314a2b13105/core/actionProxy/actionproxy.py /actionProxy/actionproxy.py

RUN mkdir -p /pythonAction
ADD https://raw.githubusercontent.com/apache/incubator-openwhisk-runtime-python/3%401.0.3/core/pythonAction/pythonrunner.py /pythonAction/pythonrunner.py

CMD ["/bin/bash", "-c", "cd /pythonAction && python -u pythonrunner.py"]