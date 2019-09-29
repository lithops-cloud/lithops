# Use the official Python image.
# https://hub.docker.com/_/python
FROM python:3.6-slim-buster

RUN pip install --upgrade setuptools six \
    && pip install --no-cache-dir \
	    gunicorn==19.9.0 \
	    pika==0.13.1 \
	    flask \
	    gevent \
	    ibm-cos-sdk \
	    redis \
	    requests \
	    numpy \

# Copy PyWren proxy  and lib to the container image.
ENV APP_HOME /pywren
WORKDIR $APP_HOME

COPY pywren_ibm_cloud ./pywren_ibm_cloud
COPY runtime/knative/pywrenproxy.py .

CMD exec gunicorn --bind :$PORT --workers 1 pywrenproxy:proxy
