# Python 3.5
#FROM python:3.5-slim-jessie

# Python 3.6
FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

ENV FLASK_PROXY_PORT 8080

RUN apt-get update \
        # add some packages required for the pip install
        && apt-get install -y \
           gcc \
           libc-dev \
           libpq-dev \
           libxslt-dev \
           libxml2-dev \
           libffi-dev \
           libssl-dev \
           zlib1g-dev \
           zip \
           unzip \
           vim \
        # add secutity updates for certain packages
        && apt-get install -y \
           e2fsprogs \
           openssl \
           tzdata \
           libgcrypt20 \
        # cleanup package lists, they are not used anymore in this image
        && rm -rf /var/lib/apt/lists/* \
        && apt-cache search linux-headers-generic \
        # create action working directory
        && mkdir -p /action \
        && mkdir -p /actionProxy \
        && mkdir -p /pythonAction

# install additional python modules
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt

ADD https://raw.githubusercontent.com/apache/openwhisk-runtime-docker/8b2e205c39d84ed5ede6b1b08cccf314a2b13105/core/actionProxy/actionproxy.py /actionProxy/actionproxy.py
ADD https://raw.githubusercontent.com/apache/openwhisk-runtime-python/3%401.0.3/core/pythonAction/pythonrunner.py /pythonAction/pythonrunner.py

CMD ["/bin/bash", "-c", "cd /pythonAction && python -u pythonrunner.py"]
