# Python 3.6
#FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

# Python 3.8
#FROM python:3.8-slim-buster

# Python 3.9
FROM python:3.9-slim-buster

# Python 3.10
#FROM python:3.10-slim-buster

RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        azure-storage-blob \
        azure-storage-queue \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib

WORKDIR /app
COPY lithops_azure_ca.zip .
RUN unzip lithops_azure_ca.zip && rm lithops_azure_ca.zip

CMD ["python", "lithopsentry.py"]
