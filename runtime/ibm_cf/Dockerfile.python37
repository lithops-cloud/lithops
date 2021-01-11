# Based on: https://github.com/ibm-functions/runtime-python/tree/master/python3.7

FROM openwhisk/actionloop-python-v3.7:4e43668

RUN  apt-get update \
     # Upgrade installed packages to get latest security fixes if the base image does not contain them already.
     && apt-get upgrade -y --no-install-recommends \
     # cleanup package lists, they are not used anymore in this image
     && rm -rf /var/lib/apt/lists/* \
     # We do not have mysql-server installed but mysql-common contains config files (/etc/mysql/my.cnf) for it.
     # We need to add some dummy entries to /etc/mysql/my.cnf to sattisfy vulnerability checking of it.
     && echo "\n[mysqld]\nssl-ca=/tmp/ca.pem\nssl-cert=/tmp/server-cert.pem\nssl-key=/tmp/server-key.pem\n" >> /etc/mysql/my.cnf

# install additional python modules
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools six && pip install --no-cache-dir -r requirements.txt
