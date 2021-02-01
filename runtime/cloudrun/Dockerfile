FROM python:3.6-slim-buster

#FROM python:3.7-slim-buster

#FROM python:3.8-slim-buster

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
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        gcsfs \
        cloudpickle \
        ps-mem \
        tblib \
        namegenerator

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_cloudrun.zip .
RUN unzip lithops_cloudrun.zip && rm lithops_cloudrun.zip

CMD exec gunicorn --bind :$PORT --workers 1 --timeout 600 lithopsproxy:proxy
