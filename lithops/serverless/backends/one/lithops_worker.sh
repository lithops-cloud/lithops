#!/bin/bash

export AMQP_URL='EDIT_ME'

install_system_dependencies() {
    echo "=== Updating apt repositories and installing system dependencies ==="
    apt-get update && apt-get install -y \
        build-essential \
        python3-dev \
        python3-pip \
        python3-venv \
        git \
        zip && \
    rm -rf /var/lib/apt/lists/*
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
}

install_python_dependencies() {
    echo "=== Upgrading pip, setuptools, and six; Installing Python dependencies ==="
    source /lithops-venv/bin/activate
    pip install --upgrade setuptools six pip
    pip install --no-cache-dir \
        boto3 \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil
}

setup_service() {
    echo "=== Copying entry_point.py to / ==="
    cp /lithops/lithops/serverless/backends/one/entry_point.py /entry_point.py

    echo "=== Creating systemd service file ==="
    cat <<EOF > /etc/systemd/system/lithops.service
[Unit]
Description=Lithops Entry Point
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/
Environment="AMQP_URL=EDIT_ME"
ExecStart=/lithops-venv/bin/python /entry_point.py \$AMQP_URL
Restart=always
RestartSec=5
StandardOutput=append:/var/log/lithops.log
StandardError=append:/var/log/lithops.log

[Install]
WantedBy=multi-user.target
EOF

    echo "=== Reloading systemd, enabling, and starting the service ==="
    systemctl daemon-reload
    systemctl enable lithops
    systemctl start lithops
}

# Main
mount_onegate
install_system_dependencies
clone_lithops_repository
create_virtualenv
install_python_dependencies
setup_service

echo "=== Lithops setup and service installation completed successfully ==="
