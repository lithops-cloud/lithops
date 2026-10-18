# Python 3.12
FROM python:3.12-slim-bookworm

# Python 3.13
#FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        zip unzip \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

# Pin setuptools<81 (PEP 517 build envs included) so legacy sdists that
# import pkg_resources still build.
RUN echo 'setuptools<81' > /tmp/constraints.txt
ENV PIP_CONSTRAINT=/tmp/constraints.txt

RUN pip install --no-cache-dir 'setuptools<81' six wheel \
    && pip install --no-cache-dir \
        gunicorn \
        flask \
        pika \
        boto3 \
        ibm-cloud-sdk-core \
        ibm-cos-sdk \
        google-cloud-storage \
        google-cloud-pubsub \
        azure-storage-blob \
        azure-storage-queue \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

ENV PORT=8080
ENV PYTHONUNBUFFERED=TRUE
ENV APP_HOME=/lithops

RUN groupadd -g 1000 lithops && useradd -m -u 1000 -g 1000 lithops

WORKDIR $APP_HOME

COPY lithops_knative.zip .
RUN unzip lithops_knative.zip && rm lithops_knative.zip && chown -R lithops:lithops $APP_HOME

USER 1000:1000

# One request at a time, as the service admits one per container. Knative
# and the Lithops worker enforce the timeout, so gunicorn does not
CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 0 lithopsproxy:proxy"]
