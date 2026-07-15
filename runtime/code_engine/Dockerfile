

# Python 3.12
FROM python:3.12-slim-bookworm

# Python 3.11
#FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six gevent \
    && pip install --no-cache-dir -r requirements.txt

ENV PORT=8080
ENV CONCURRENCY=1
ENV TIMEOUT=600
ENV PYTHONUNBUFFERED=TRUE

ENV APP_HOME=/lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip

# CE jobs override the container command. Gunicorn is kept for legacy Knative-style starts.
CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsentry:proxy"]
