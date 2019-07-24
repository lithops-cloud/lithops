# Based on: https://github.com/ibm-functions/runtime-python/tree/master/python3.6

FROM python:3.5-slim-jessie

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

COPY requirements.txt requirements.txt

RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt

# create action working directory
RUN mkdir -p /action

RUN mkdir -p /actionProxy
ADD https://raw.githubusercontent.com/apache/incubator-openwhisk-runtime-docker/8b2e205c39d84ed5ede6b1b08cccf314a2b13105/core/actionProxy/actionproxy.py /actionProxy/actionproxy.py

RUN mkdir -p /pythonAction
ADD https://raw.githubusercontent.com/apache/incubator-openwhisk-runtime-python/3%401.0.3/core/pythonAction/pythonrunner.py /pythonAction/pythonrunner.py

CMD ["/bin/bash", "-c", "cd /pythonAction && python -u pythonrunner.py"]
