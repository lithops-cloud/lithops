# Python 3.6
FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        gunicorn==19.9.0 \
        pika==0.13.1 \
        flask \
        gevent \
        glob2 \
        ibm-cos-sdk \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy

# Copy PyWren proxy and lib to the container image.
ENV APP_HOME /pywren
WORKDIR $APP_HOME

COPY pywren_knative.zip .
RUN unzip pywren_knative.zip && rm pywren_knative.zip

CMD exec gunicorn --bind :$PORT --workers 1 pywrenproxy:proxy
