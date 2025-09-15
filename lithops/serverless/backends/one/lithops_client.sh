#!/bin/bash

install_python3_venv() {
    echo "=== Installing python3-venv ==="
    apt-get update && apt-get install -y python3-venv
}

mount_onegate() {
    mkdir /mnt/context
    mount /dev/cdrom /mnt/context
}

clone_lithops_repository() {
    echo "=== Cloning the Lithops repository into /lithops ==="
    git clone https://github.com/OpenNebula/lithops.git /lithops
    git checkout f-748
}

create_virtualenv() {
    echo "=== Creating a Python virtual environment in /lithops-venv ==="
    python3 -m venv /lithops-venv
    source /lithops-venv/bin/activate
}

install_lithops() {
    echo "=== Installing Lithops and dependencies ==="
    cd /lithops
    python3 setup.py install
    pip install lithops[aws]
    pip install --no-deps -e .
}

setup_configuration() {
    echo "=== Setting up Lithops configuration ==="
    mkdir -p /etc/lithops
    cat <<EOF > /etc/lithops/config
lithops:
  monitoring: rabbitmq
  backend: one
  storage: aws_s3

rabbitmq:
  amqp_url: EDIT_ME

one:
  worker_processes: 2
  runtime_memory: 512
  runtime_timeout: 600
  runtime_cpu: 2
  amqp_url: EDIT_ME
  max_workers: 3
  min_workers: 1
  autoscale: none

aws:
  region: EDIT_ME
  access_key_id: EDIT_ME
  secret_access_key: EDIT_ME
EOF
}

# Main
mount_onegate
install_python3_venv
clone_lithops_repository
create_virtualenv
install_lithops
setup_configuration

echo "=== Lithops setup and configuration completed successfully ==="