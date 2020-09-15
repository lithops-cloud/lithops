# Python 3.5
#FROM python:3.5-slim-jessie

# Python 3.6
FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

ENV FLASK_PROXY_PORT 8080

RUN apt-get update \
        # Upgrade installed packages to get latest security fixes if the base image does not contain them already.
        && apt-get upgrade -y --no-install-recommends \
        # add some packages required for the pip install
        && apt-get install -y --no-install-recommends \
           gcc \
           libc-dev \
           libxslt-dev \
           libxml2-dev \
           libffi-dev \
           libssl-dev \
           zip \
           unzip \
           vim \
        # cleanup package lists, they are not used anymore in this image
        && rm -rf /var/lib/apt/lists/* \
        && apt-cache search linux-headers-generic

# install additional python modules
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt
        
# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_betabs.zip .
RUN unzip lithops_betabs.zip
RUN rm lithops_betabs.zip
