import os
import json
from enum import Enum

from lithops.constants import (
    SA_INSTALL_DIR,
    SA_SETUP_LOG_FILE,
    SA_CONFIG_FILE,
    SA_WORKER_DATA_FILE,
    SA_MASTER_DATA_FILE,
    SA_WORKER_SERVICE_PORT,
    SA_WORKER_LOG_FILE,
    SA_SETUP_DONE_FILE
)


class StandaloneMode(Enum):
    CONSUME = "consume"
    CREATE = "create"
    REUSE = "reuse"


class WorkerStatus(Enum):
    STARTING = "starting"
    STARTED = "started"
    ERROR = "error"
    INSTALLING = "installing"
    ACTIVE = "active"
    IDLE = "idle"
    BUSY = "busy"
    STOPPED = "stopped"


class JobStatus(Enum):
    SUBMITTED = "submitted"
    PENDING = "pending"
    RUNNING = "running"
    DONE = 'done'
    CANCELED = 'canceled'


class LithopsValidationError(Exception):
    pass


MASTER_SERVICE_NAME = 'lithops-master.service'
MASTER_SERVICE_FILE = f"""
[Unit]
Description=Lithops Master Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 {SA_INSTALL_DIR}/master.py
Restart=always

[Install]
WantedBy=multi-user.target
"""

WORKER_SERVICE_NAME = 'lithops-worker.service'
WORKER_SERVICE_FILE = """
[Unit]
Description=Lithops Worker Service
After=network.target
RestartSec=2s
StartLimitBurst=1
StartLimitIntervalSec=5

[Service]
ExecStartPre={0}
ExecStart={1}
ExecStop={2}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

CLOUD_CONFIG_WORKER_PK = """
#cloud-config
users:
    - name: {0}
      ssh_authorized_keys:
        - {1}
      sudo: ALL=(ALL) NOPASSWD:ALL
      groups: sudo
      shell: /bin/bash
"""

CLOUD_CONFIG_WORKER = """
#cloud-config
bootcmd:
    - echo '{0}:{1}' | chpasswd
    - sed -i '/PasswordAuthentication no/c\PasswordAuthentication yes' /etc/ssh/sshd_config
    - echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
runcmd:
    - echo '{0}:{1}' | chpasswd
    - sed -i '/PasswordAuthentication no/c\PasswordAuthentication yes' /etc/ssh/sshd_config
    - echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
    - systemctl restart sshd
"""


def get_host_setup_script(docker=True):
    """
    Returns the script necessary for installing a lithops VM host
    """
    script = f"""#!/bin/bash
    mkdir -p {SA_INSTALL_DIR};

    wait_internet_connection(){{
    echo "--> Checking internet connection"
    while ! (ping -c 1 -W 1 8.8.8.8| grep -q 'statistics'); do
    echo "Waiting for 8.8.8.8 - network interface might be down..."
    sleep 1
    done;
    }}

    install_packages(){{
    export DOCKER_REQUIRED={str(docker).lower()};
    command -v docker >/dev/null 2>&1 || {{ export INSTALL_DOCKER=true; export INSTALL_LITHOPS_DEPS=true;}};
    command -v unzip >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    command -v pip3 >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};

    if [ "$INSTALL_DOCKER" = true ] && [ "$DOCKER_REQUIRED" = true ]; then
    wait_internet_connection;
    echo "--> Installing Docker"
    apt-get update;
    apt-get install apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y;
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -;
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable";
    fi;

    if [ "$INSTALL_LITHOPS_DEPS" = true ]; then
    wait_internet_connection;
    echo "--> Installing Lithops system dependencies"
    apt-get update;

    if [ "$INSTALL_DOCKER" = true ] && [ "$DOCKER_REQUIRED" = true ]; then
    apt-get install unzip redis-server python3-pip docker-ce docker-ce-cli containerd.io -y --fix-missing;
    else
    apt-get install unzip redis-server python3-pip -y --fix-missing;
    fi;
    sudo systemctl enable redis-server.service;
    sed -i 's/^bind 127.0.0.1 ::1/bind 0.0.0.0/' /etc/redis/redis.conf;
    sudo systemctl restart redis-server.service;

    fi;

    if [[ ! $(pip3 list|grep "lithops") ]]; then
    wait_internet_connection;
    echo "--> Installing Lithops python dependencies"
    pip3 install -U pip flask gevent lithops[all];
    fi;
    }}
    install_packages >> {SA_SETUP_LOG_FILE} 2>&1
    touch {SA_SETUP_DONE_FILE};
    """
    return script


def docker_login(config):
    backend = config['backend']
    if all(k in config[backend] for k in ("docker_server", "docker_user", "docker_password")):
        user = config[backend]['docker_user']
        passwd = config[backend]['docker_password']
        server = config[backend]['docker_server']
        return f"""docker login -u {user} -p {passwd} {server} >> /tmp/kuku 2>&1
    """
    return ""


def get_master_setup_script(config, vm_data):
    """
    Returns master VM installation script
    """
    script = docker_login(config)
    script += f"""
    setup_host(){{
    unzip -o /tmp/lithops_standalone.zip -d {SA_INSTALL_DIR};
    mv /tmp/lithops_standalone.zip {SA_INSTALL_DIR};
    echo '{json.dumps(vm_data)}' > {SA_MASTER_DATA_FILE};
    echo '{json.dumps(config)}' > {SA_CONFIG_FILE};
    }}
    setup_host >> {SA_SETUP_LOG_FILE} 2>&1;
    setup_service(){{
    echo '{MASTER_SERVICE_FILE}' > /etc/systemd/system/{MASTER_SERVICE_NAME};
    chmod 644 /etc/systemd/system/{MASTER_SERVICE_NAME};
    systemctl daemon-reload;
    systemctl stop {MASTER_SERVICE_NAME};
    systemctl enable {MASTER_SERVICE_NAME};
    systemctl start {MASTER_SERVICE_NAME};
    }}
    setup_service >> {SA_SETUP_LOG_FILE} 2>&1;
    USER_HOME=$(eval echo ~${{SUDO_USER}});
    generate_ssh_key(){{
    echo '    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null' >> /etc/ssh/ssh_config;
    ssh-keygen -f $USER_HOME/.ssh/lithops_id_rsa -t rsa -N '';
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh/lithops_id_rsa*;
    cp $USER_HOME/.ssh/lithops_id_rsa $USER_HOME/.ssh/id_rsa
    cp $USER_HOME/.ssh/lithops_id_rsa.pub $USER_HOME/.ssh/id_rsa.pub
    cp $USER_HOME/.ssh/* /root/.ssh;
    echo '127.0.0.1 lithops-master' >> /etc/hosts;
    cat $USER_HOME/.ssh/id_rsa.pub >> $USER_HOME/.ssh/authorized_keys;
    }}
    test -f $USER_HOME/.ssh/lithops_id_rsa || generate_ssh_key >> {SA_SETUP_LOG_FILE} 2>&1;
    echo 'tail -f -n 100 /tmp/lithops-*/master-service.log'>>  $USER_HOME/.bash_history
    """
    return script


def get_worker_setup_script(config, vm_data):
    """
    Returns worker VM installation script
    this script is expected to be executed only from Master VM
    """
    if config['runtime'].startswith(('python', '/')):
        cmd_pre = cmd_stop = "id"
        cmd_start = f"/usr/bin/python3 {SA_INSTALL_DIR}/worker.py"
    else:
        cmd_pre = '-docker rm -f lithops_worker'
        cmd_start = 'docker run --rm --name lithops_worker '
        cmd_start += '--gpus all ' if config["use_gpu"] else ''
        cmd_start += f'--user {os.getuid()}:{os.getgid()} '
        cmd_start += f'--env USER={os.getenv("USER", "root")} --env DOCKER=Lithops '
        cmd_start += f'-p {SA_WORKER_SERVICE_PORT}:{SA_WORKER_SERVICE_PORT} '
        cmd_start += f'-v {SA_INSTALL_DIR}:{SA_INSTALL_DIR} -v /tmp:/tmp '
        cmd_start += f'--entrypoint "python3" {config["runtime"]} {SA_INSTALL_DIR}/worker.py'
        cmd_stop = '-docker rm -f lithops_worker'

    script = docker_login(config)
    script += f"""
    setup_host(){{
    unzip -o /tmp/lithops_standalone.zip -d {SA_INSTALL_DIR};
    rm /tmp/lithops_standalone.zip;
    echo '{json.dumps(vm_data)}' > {SA_WORKER_DATA_FILE};
    echo '{json.dumps(config)}' > {SA_CONFIG_FILE};
    }}
    setup_host >> {SA_SETUP_LOG_FILE} 2>&1;
    USER_HOME=$(eval echo ~${{SUDO_USER}});
    setup_service(){{
    echo '{WORKER_SERVICE_FILE.format(cmd_pre, cmd_start, cmd_stop)}' > /etc/systemd/system/{WORKER_SERVICE_NAME};
    chmod 644 /etc/systemd/system/{WORKER_SERVICE_NAME};
    systemctl daemon-reload;
    systemctl stop {WORKER_SERVICE_NAME};
    systemctl enable {WORKER_SERVICE_NAME};
    systemctl start {WORKER_SERVICE_NAME};
    }}
    setup_service >> {SA_SETUP_LOG_FILE} 2>&1
    echo '{vm_data['master_ip']} lithops-master' >> /etc/hosts
    echo 'tail -f -n 100 {SA_WORKER_LOG_FILE}'>> $USER_HOME/.bash_history
    """

    if "ssh_credentials" in vm_data:
        ssh_user = vm_data['ssh_credentials']['username']
        home_dir = '/root' if ssh_user == 'root' else f'/home/{ssh_user}'
        try:
            master_pub_key = open(f'{home_dir}/.ssh/lithops_id_rsa.pub', 'r').read()
        except Exception:
            master_pub_key = ''
        script += f"""
        if ! grep -qF "{master_pub_key}" "$USER_HOME/.ssh/authorized_keys"; then
            echo "{master_pub_key}" >> $USER_HOME/.ssh/authorized_keys;
        fi
        """
    return script
