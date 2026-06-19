import os
import re
import json
import shlex
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


def prepare_standalone_clean(backend, load_cache_fn):
    """
    Load persisted stack metadata from disk when the backend has a cache file.

    Standalone cloud backends call this at the start of clean() so cleanup works
    even when clean() is invoked without a prior init() in the same process.
    """
    if backend.is_initialized():
        load_cache_fn()


def standalone_clean_stop_early(backend, stack_data, delete_cache_fn, all_flag):
    """
    Common clean() early exits for consume mode and missing stack metadata.

    Returns True when no further cloud resource cleanup is required.
    """
    if backend.mode == StandaloneMode.CONSUME.value:
        delete_cache_fn()
        return True
    if not stack_data:
        if all_flag:
            delete_cache_fn()
        return True
    return False


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


def _normalize_package_list(packages):
    if not packages:
        return []
    if isinstance(packages, str):
        return [p.strip() for p in packages.split() if p.strip()]
    return [str(p).strip() for p in packages if str(p).strip()]


def _format_apt_packages_for_shell(packages):
    safe = []
    for package in _normalize_package_list(packages):
        if not re.match(r'^[a-z0-9][a-z0-9.+~-]*$', package, re.IGNORECASE):
            raise LithopsValidationError(
                f'Invalid apt package name "{package}" in extra_apt_packages'
            )
        safe.append(package)
    return ' '.join(safe)


def _format_pip_packages_for_shell(packages):
    quoted = []
    for package in _normalize_package_list(packages):
        if re.search(r'[;&|`$(){}]', package):
            raise LithopsValidationError(
                f'Invalid pip package spec "{package}" in extra_python_packages'
            )
        quoted.append(shlex.quote(package))
    return ' '.join(quoted)


def install_script_kwargs_from_config(config=None):
    """
    Build keyword arguments for get_host_setup_script() from standalone config.
    """
    config = config or {}
    return {
        'lithops_pip_spec': lithops_pip_spec_from_config(config),
        'extra_apt_packages': _format_apt_packages_for_shell(config.get('extra_apt_packages')),
        'extra_python_packages': _format_pip_packages_for_shell(config.get('extra_python_packages')),
    }


def lithops_pip_spec_from_config(config=None, default='lithops'):
    """
    Build a minimal pip spec from lithops config (avoid lithops[all] on VMs).
    Standalone master/workers always need the redis extra for the job queue.
    """
    if not config:
        return default

    extras = {'redis'}
    lithops_cfg = config.get('lithops') or {}
    for key in ('backend', 'storage'):
        name = (config.get(key) or lithops_cfg.get(key) or '').lower()
        if name.startswith('gcp'):
            extras.add('gcp')
        elif name.startswith('aws') or name in ('aws_s3', 'aws_sqs'):
            extras.add('aws')
        elif name.startswith('azure'):
            extras.add('azure')
        elif name.startswith('ibm'):
            extras.add('ibm')
        elif name.startswith('aliyun'):
            extras.add('aliyun')
        elif name in ('oracle', 'oci', 'oracle_storage'):
            extras.add('oracle')

    cloud_extras = extras - {'redis'}
    if not cloud_extras:
        return 'lithops[redis]'
    return f"lithops[{','.join(sorted(extras))}]"


def get_host_setup_script(
    docker=True,
    run_install=True,
    lithops_pip_spec='lithops',
    extra_apt_packages='',
    extra_python_packages='',
):
    """
    Returns the script necessary for installing a lithops VM host.
    Set run_install=False when appending master/worker setup (they run install first).
    extra_apt_packages/extra_python_packages are pre-validated space-separated strings.
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

    apt_install(){{
    # Serialize apt and recover from interrupted/corrupt package lists.
    flock -w 600 /var/lib/dpkg/lock-frontend apt-get "$@" || {{
        echo "--> apt failed, repairing package lists and retrying"
        rm -rf /var/lib/apt/lists/partial/*
        apt-get clean
        apt-get update
        flock -w 600 /var/lib/dpkg/lock-frontend apt-get "$@"
    }}
    }}

    configure_redis_for_standalone(){{
    # Workers connect to the master private IP; Redis must not listen on loopback only.
    if [ ! -f /etc/redis/redis.conf ]; then
        return 0
    fi
    echo "--> Configuring Redis for standalone workers (bind 0.0.0.0)"
    sed -i -E 's/^bind .*/bind 0.0.0.0 -::1/' /etc/redis/redis.conf
    if grep -q '^protected-mode yes' /etc/redis/redis.conf; then
        sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf
    fi
    systemctl enable redis-server.service
    systemctl restart redis-server.service
    }}

    install_packages(){{
    set -e
    export DEBIAN_FRONTEND=noninteractive
    export DOCKER_REQUIRED={str(docker).lower()};
    command -v docker >/dev/null 2>&1 || {{ export INSTALL_DOCKER=true; export INSTALL_LITHOPS_DEPS=true;}};
    command -v unzip >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    command -v pip3 >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};

    if [ "$INSTALL_DOCKER" = true ] && [ "$DOCKER_REQUIRED" = true ]; then
    wait_internet_connection;
    echo "--> Installing Docker repository"
    apt_install update
    apt_install install -y apt-transport-https ca-certificates curl gnupg software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    DOCKER_APT="deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg]"
    DOCKER_APT="$DOCKER_APT https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    echo "$DOCKER_APT" > /etc/apt/sources.list.d/docker.list
    fi;

    if [ "$INSTALL_LITHOPS_DEPS" = true ]; then
    wait_internet_connection;
    echo "--> Installing Lithops system dependencies"
    apt_install update

    if [ "$INSTALL_DOCKER" = true ] && [ "$DOCKER_REQUIRED" = true ]; then
    apt_install install -y unzip redis-server python3-pip docker-ce docker-ce-cli containerd.io
    else
    apt_install install -y unzip redis-server python3-pip
    fi;
    configure_redis_for_standalone

    fi;

    EXTRA_APT="{extra_apt_packages}"
    if [ -n "$EXTRA_APT" ]; then
    wait_internet_connection;
    apt_install update
    echo "--> Installing extra apt packages: $EXTRA_APT"
    apt_install install -y $EXTRA_APT
    fi;

    if ! pip3 list 2>/dev/null | grep -q lithops; then
    wait_internet_connection;
    echo "--> Installing Lithops python dependencies ({lithops_pip_spec})"
    export PIP_BREAK_SYSTEM_PACKAGES=1
    # --ignore-installed: do not uninstall Debian python packages (avoids RECORD errors)
    pip3 install --ignore-installed -U pip
    pip3 install --ignore-installed flask gevent {lithops_pip_spec}
    if echo "{lithops_pip_spec}" | grep -q ibm; then
    echo "--> Upgrading pyOpenSSL/cryptography (required for ibm_cos on Ubuntu 24.04)"
    pip3 install --ignore-installed --upgrade 'pyopenssl>=24.0.0' 'cryptography>=42.0.0'
    fi;
    fi;

    EXTRA_PY="{extra_python_packages}"
    if [ -n "$EXTRA_PY" ]; then
    echo "--> Installing extra python packages: $EXTRA_PY"
    export PIP_BREAK_SYSTEM_PACKAGES=1
    pip3 install --ignore-installed $EXTRA_PY
    fi;
    }}
    """
    if run_install:
        script += f"install_packages >> {SA_SETUP_LOG_FILE} 2>&1 && touch {SA_SETUP_DONE_FILE};\n"
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
    setup_service(){{
    configure_redis_for_standalone >> {SA_SETUP_LOG_FILE} 2>&1
    echo '{MASTER_SERVICE_FILE}' > /etc/systemd/system/{MASTER_SERVICE_NAME};
    chmod 644 /etc/systemd/system/{MASTER_SERVICE_NAME};
    systemctl daemon-reload;
    systemctl stop {MASTER_SERVICE_NAME};
    systemctl enable {MASTER_SERVICE_NAME};
    systemctl start {MASTER_SERVICE_NAME};
    }}
    USER_HOME=$(eval echo ~${{SUDO_USER}});
    generate_ssh_key(){{
    echo '    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null' >> /etc/ssh/ssh_config;
    mkdir -p $USER_HOME/.ssh;
    chmod 700 $USER_HOME/.ssh;
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh;
    ssh-keygen -f $USER_HOME/.ssh/lithops_id_rsa -t rsa -N '';
    cp $USER_HOME/.ssh/lithops_id_rsa $USER_HOME/.ssh/id_rsa
    cp $USER_HOME/.ssh/lithops_id_rsa.pub $USER_HOME/.ssh/id_rsa.pub
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh/lithops_id_rsa* $USER_HOME/.ssh/id_rsa $USER_HOME/.ssh/id_rsa.pub
    chmod 600 $USER_HOME/.ssh/lithops_id_rsa $USER_HOME/.ssh/id_rsa
    chmod 644 $USER_HOME/.ssh/lithops_id_rsa.pub $USER_HOME/.ssh/id_rsa.pub
    cp $USER_HOME/.ssh/lithops_id_rsa /root/.ssh/lithops_id_rsa
    cp $USER_HOME/.ssh/lithops_id_rsa.pub /root/.ssh/lithops_id_rsa.pub
    chmod 600 /root/.ssh/lithops_id_rsa
    echo '127.0.0.1 lithops-master' >> /etc/hosts;
    cat $USER_HOME/.ssh/id_rsa.pub >> $USER_HOME/.ssh/authorized_keys;
    }}
    install_packages >> {SA_SETUP_LOG_FILE} 2>&1 && touch {SA_SETUP_DONE_FILE} && \\
    setup_host >> {SA_SETUP_LOG_FILE} 2>&1 && \\
    setup_service >> {SA_SETUP_LOG_FILE} 2>&1 && \\
    (test -f $USER_HOME/.ssh/lithops_id_rsa || generate_ssh_key >> {SA_SETUP_LOG_FILE} 2>&1)
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
    USER_HOME=$(eval echo ~${{SUDO_USER}});
    setup_service(){{
    echo '{WORKER_SERVICE_FILE.format(cmd_pre, cmd_start, cmd_stop)}' > /etc/systemd/system/{WORKER_SERVICE_NAME};
    chmod 644 /etc/systemd/system/{WORKER_SERVICE_NAME};
    systemctl daemon-reload;
    systemctl stop {WORKER_SERVICE_NAME};
    systemctl enable {WORKER_SERVICE_NAME};
    systemctl start {WORKER_SERVICE_NAME};
    }}
    install_packages >> {SA_SETUP_LOG_FILE} 2>&1 && touch {SA_SETUP_DONE_FILE} && \\
    setup_host >> {SA_SETUP_LOG_FILE} 2>&1 && \\
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
