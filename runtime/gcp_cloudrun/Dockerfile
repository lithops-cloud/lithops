# Python 3.6
#FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

# Python 3.8
FROM python:3.8-slim-buster

# Python 3.9
#FROM python:3.9-slim-buster

RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        wheel \
        gunicorn \
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
        tblib \
        cryptography \
        httplib2 \
        google-cloud-storage \
        google-api-python-client \
        gcsfs \
        google-auth

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_cloudrun.zip .
RUN unzip lithops_cloudrun.zip && rm lithops_cloudrun.zip

CMD exec gunicorn --bind :$PORT lithopsproxy:proxy
