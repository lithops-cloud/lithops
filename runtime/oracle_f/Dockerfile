# Python 3.6
#FROM python:3.6-slim-buster

# Python 3.7
#FROM python:3.7-slim-buster

# Python 3.8
#FROM python:3.8-slim-buster

# Python 3.9
FROM python:3.9-slim-buster

RUN apt-get update \
    && apt-get install -y \
    zip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
    fn \
    fdk \
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
    tblib \
    oci \
    psutil

ARG FUNCTION_DIR="/function"

# Copy function code
RUN mkdir -p ${FUNCTION_DIR}
ENV FN_LISTENER=unix:/tmp/fn.sock
ENV FN_FORMAT=http-stream

WORKDIR ${FUNCTION_DIR}

COPY lithops_oracle.zip ${FUNCTION_DIR}
RUN unzip lithops_oracle.zip \
    && rm lithops_oracle.zip \
    && mkdir handler \
    && touch handler/__init__.py \
    && mv entry_point.py handler/


ENV PYTHONPATH "${PYTHONPATH}:${FUNCTION_DIR}"
ENTRYPOINT ["/usr/local/bin/fdk", "handler/entry_point.py", "handler"]
