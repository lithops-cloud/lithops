# Python 3.6
#FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

# Python 3.8
FROM python:3.8-slim-buster

# Python 3.9
#FROM python:3.9-slim-buster

# Python 3.10
#FROM python:3.10-slim-buster

RUN apt-get update \
    && apt-get install -y \
      zip \
      && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        boto3 \
        pika \
        glob2 \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        matplotlib

ARG FUNCTION_DIR="/function"

# Copy function code
RUN mkdir -p ${FUNCTION_DIR}

# Update pip
RUN pip install --upgrade --ignore-installed pip wheel six setuptools \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        fn \
        boto3 \
        redis \
        httplib2 \
        requests \
        numpy \
        scipy \
        pandas \
        pika \
        kafka-python \
        cloudpickle \
        ps-mem \
        tblib

WORKDIR ${FUNCTION_DIR}

COPY lithops_oracle.zip ${FUNCTION_DIR}
RUN unzip lithops_oracle.zip \
    && rm lithops_oracle.zip \
    && mkdir handler \
    && touch handler/__init__.py \
    && mv entry_point.py handler/


ENTRYPOINT [ "/usr/local/bin/python", "-m", "fn_fdk" ]
CMD [ "handler.entry_point.main" ]