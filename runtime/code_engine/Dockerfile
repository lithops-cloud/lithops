

# Python 3.12
FROM python:3.12-slim-bookworm

# Python 3.11
#FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six \
    && pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=TRUE

ENV APP_HOME=/lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip

# Code Engine job runs override the command with `python /lithops/lithopsentry.py`
CMD ["python", "lithopsentry.py"]
