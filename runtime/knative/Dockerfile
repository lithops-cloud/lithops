FROM python

RUN apt-get update && apt-get install -y \
        gcc \
        libc-dev \
        libxslt-dev \
        libxml2-dev \
        libffi-dev \
        libssl-dev \
        zip \
        unzip \
        vim \
        net-tools \
        iputils-ping \
        && rm -rf /var/lib/apt/lists/*

RUN apt-cache search linux-headers-generic

COPY requirements.txt requirements.txt

RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY app.py .
COPY pywren_ibm_cloud ./pywren_ibm_cloud

# Service must listen to $PORT environment variable.
ENV PORT 8080

# Run the web service on container startup.
CMD ["python", "app.py"]
