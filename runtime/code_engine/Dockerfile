# Python 3.6
#FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

# Python 3.8
#FROM python:3.8-slim-buster

# Python 3.9
#FROM python:3.9-slim-buster

# Python 3.10
FROM python:3.10-slim-buster

# Python 3.11
# FROM python:3.11-slim-buster

RUN apt-get update \
    # add the required packages
    && apt-get install -y unzip \
    # cleanup package lists, they are not used anymore in this image
    && rm -rf /var/lib/apt/lists/* \
    && apt-cache search linux-headers-generic

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six gevent && pip install --no-cache-dir -r requirements.txt

ENV PORT 8080
ENV CONCURRENCY 1
ENV TIMEOUT 600
ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip

CMD exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsentry:proxy
