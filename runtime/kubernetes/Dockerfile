# Python 3.8
#FROM python:3.8-slim-bookworm

# Python 3.9
#FROM python:3.9-slim-bookworm

# Python 3.10
FROM python:3.10-slim-bookworm

# Python 3.11
#FROM python:3.11-slim-bookworm

# Python 3.12
#FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
        zip redis-server curl \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        flask \
        pika \
        boto3 \
        ibm-cloud-sdk-core \
        ibm-cos-sdk \
        redis \
        gevent \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_k8s.zip .
RUN unzip lithops_k8s.zip && rm lithops_k8s.zip
