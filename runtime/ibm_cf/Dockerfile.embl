# Minimal Docker image for PyWren

# Python 3.7.5
FROM python:3.7.5-slim-buster

ENV FLASK_PROXY_PORT 8080

RUN pip install --upgrade pip setuptools six \
    && pip install --no-cache-dir \
        simplejson==3.16.0 \
        httplib2==0.13.0 \
        kafka_python==1.4.6 \
        lxml==4.3.1 \
        python-dateutil==2.8.0 \
        pika==0.13.1 \
        flask==1.1.1 \
        gevent==1.4.0 \
        ibm-cos-sdk==2.6.0 \
        redis==3.3.8 \
        requests==2.22.0 \
        numpy==1.17.2 \
        # Modules for annotation-pipeline:
        cpyMSpec==0.3.5 \
        pyMSpec==0.1.2 \
        cpyImagingMSpec==0.2.4 \
        pyImagingMSpec==0.1.4 \
        pandas==0.25.1 \
        scipy==1.3.1 \
        msgpack==0.6.2 \
        msgpack-numpy==0.4.4.3 \
	    pyimzML==1.3.0

# create action working directory
RUN mkdir -p /action \
    && mkdir -p /actionProxy \
    && mkdir -p /pythonAction

ADD https://raw.githubusercontent.com/apache/openwhisk-runtime-docker/8b2e205c39d84ed5ede6b1b08cccf314a2b13105/core/actionProxy/actionproxy.py /actionProxy/actionproxy.py
ADD https://raw.githubusercontent.com/apache/openwhisk-runtime-python/3%401.0.3/core/pythonAction/pythonrunner.py /pythonAction/pythonrunner.py

CMD ["/bin/bash", "-c", "cd /pythonAction && python -u pythonrunner.py"]
