# Python 3.10
FROM python:3.10-slim-bookworm

# Python 3.11
#FROM python:3.11-slim-bookworm

# Python 3.12
#FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        zip unzip redis-server curl ca-certificates \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

# Pin setuptools<81 (PEP 517 build envs included) so legacy sdists that
# import pkg_resources still build.
RUN echo 'setuptools<81' > /tmp/constraints.txt
ENV PIP_CONSTRAINT=/tmp/constraints.txt

RUN pip install --no-cache-dir 'setuptools<81' six wheel \
    && pip install --no-cache-dir \
        flask \
        pika \
        boto3 \
        ibm-cloud-sdk-core \
        ibm-cos-sdk \
        redis \
        gevent \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

ENV PYTHONUNBUFFERED=TRUE
ENV APP_HOME=/lithops

# Non-root user matches the PSS Restricted recipe in docs/source/compute_config/kubernetes.md.
RUN groupadd -g 1000 lithops && useradd -m -u 1000 -g 1000 lithops

WORKDIR $APP_HOME

COPY lithops_k8s.zip .
RUN unzip lithops_k8s.zip && rm lithops_k8s.zip && chown -R lithops:lithops $APP_HOME

USER 1000:1000
