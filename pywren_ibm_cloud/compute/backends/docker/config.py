import sys
import multiprocessing
from pywren_ibm_cloud.utils import version_str

RUNTIME_DEFAULT_35 = 'pywren-docker-runtime-v3.5:latest'
RUNTIME_DEFAULT_36 = 'pywren-docker-runtime-v3.6:latest'
RUNTIME_DEFAULT_37 = 'pywren-docker-runtime-v3.7:latest'
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes
RUNTIME_MEMORY_DEFAULT = 256  # 256 MB

_DOCKERFILE_DEFAULT = """
RUN apt-get update && apt-get install -y \
        git

RUN pip install --upgrade pip setuptools six \
    && pip install --no-cache-dir \
        pika==0.13.1 \
        ibm-cos-sdk \
        redis \
        requests \
        numpy

# Copy PyWren app to the container image.
ENV APP_HOME /pywren
WORKDIR $APP_HOME

RUN git clone https://github.com/pywren/pywren-ibm-cloud && cd pywren-ibm-cloud && pip install .

# entry_point.py is automatically generated. Do not modify next lines!
COPY entry_point.py .

ENTRYPOINT ["python", "entry_point.py"]
CMD []
"""

DOCKERFILE_DEFAULT_35 = """
FROM python:3.5-slim-buster
""" + _DOCKERFILE_DEFAULT

DOCKERFILE_DEFAULT_36 = """
FROM python:3.6-slim-buster
""" + _DOCKERFILE_DEFAULT

DOCKERFILE_DEFAULT_37 = """
FROM python:3.7-slim-buster
""" + _DOCKERFILE_DEFAULT


def load_config(config_data):
    if 'runtime_memory' not in config_data['pywren']:
        config_data['pywren']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    if 'runtime' not in config_data['pywren']:
        this_version_str = version_str(sys.version_info)
        if this_version_str == '3.5':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_35
        elif this_version_str == '3.6':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_36
        elif this_version_str == '3.7':
            config_data['pywren']['runtime'] = RUNTIME_DEFAULT_37

    if 'docker' not in config_data:
        config_data['docker'] = {}

    if 'workers' in config_data['pywren']:
        config_data['docker']['workers'] = config_data['pywren']['workers']
    else:
        if 'workers' not in config_data['docker']:
            total_cores = multiprocessing.cpu_count()
            config_data['pywren']['workers'] = total_cores
            config_data['docker']['workers'] = total_cores
        else:
            config_data['pywren']['workers'] = config_data['docker']['workers']
