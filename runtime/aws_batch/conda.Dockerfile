# Python 3.6
#FROM continuumio/miniconda3:4.5.4 

# Python 3.7
#FROM continuumio/miniconda3:4.7.12

# Python 3.8
#FROM continuumio/miniconda3:4.9.2

# Python 3.9
FROM continuumio/miniconda3:4.10.3

# YOU MUST PIN THE PYTHON VERSION TO PREVENT IT TO BE UPDATED
# For python 3.6 use "python==3.6.5"
# For python 3.7 use "python==3.7.4"
# For python 3.8 use "python==3.8.5"
# For python 3.9 use "python==3.9.5"
RUN echo "python==3.9.13" >> /opt/conda/conda-meta/pinned

RUN apt-get --allow-releaseinfo-change update \
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
           unzip \
           make \
        # cleanup package lists, they are not used anymore in this image
        && rm -rf /var/lib/apt/lists/* \
        && apt-cache search linux-headers-generic

# Put here your conda dependencies...
# RUN conda update -n base conda && conda install -c conda-forge opencv && conda install sortedcontainers gevent-websocket && conda clean --all

RUN pip install --upgrade --ignore-installed pip wheel six setuptools

RUN pip install --upgrade --no-cache-dir --ignore-installed \
        awslambdaric \
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
        tblib \
        psutil
        # Put here your pip dependencies...

ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_aws_batch.zip .
RUN unzip lithops_aws_batch.zip && rm lithops_aws_batch.zip

ENTRYPOINT python entry_point.py
