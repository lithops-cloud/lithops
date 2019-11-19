# Use the official Python image.
# https://hub.docker.com/_/python
FROM python:3.6-slim-buster

RUN apt-get update && apt-get install -y \
        git

RUN pip install --upgrade pip setuptools six \
    && pip install --no-cache-dir \
	    pika==0.13.1 \
	    ibm-cos-sdk \
	    redis \
	    requests \
	    numpy
	   


# Copy PyWren app to the container image.
ENV APP_HOME /pywren
WORKDIR $APP_HOME

RUN git clone https://github.com/JosepSampe/pywren-ibm-cloud -b pywren-dev && cd pywren-ibm-cloud && pip install .

COPY app.py .

ENTRYPOINT ["python", "app.py"]
CMD []