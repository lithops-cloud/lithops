FROM python:3.6-slim-buster

RUN pip install --upgrade setuptools six \
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

COPY pywren_ibm_cloud ./pywren_ibm_cloud
COPY pywren_ibm_cloud/compute/backends/knative/entry_point.py pywrenproxy.py

CMD exec gunicorn --bind :$PORT --workers 1 pywrenproxy:proxy
