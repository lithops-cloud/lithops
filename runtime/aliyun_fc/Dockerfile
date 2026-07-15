# Reference Dockerfile for Aliyun FC custom-container mode.
# Lithops generates this automatically when deploy_mode is custom-container.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools \
    && pip install --no-cache-dir \
        gunicorn flask gevent six pika redis requests PyYAML oss2 \
        cloudpickle ps-mem tblib psutil

ENV APP_HOME=/function
WORKDIR ${APP_HOME}

COPY lithops_aliyun_fc.zip .
RUN unzip lithops_aliyun_fc.zip && rm lithops_aliyun_fc.zip

# Optional: add extra dependencies
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

ENV CAPort=9000
CMD exec gunicorn --bind 0.0.0.0:${CAPort} --workers 1 --timeout 600 container_entry_point:app
