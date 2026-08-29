import os
import re
import json
import shlex
from enum import Enum
from typing import Any, Dict, List, Tuple

from lithops.localhost.config import LocalhostEnvironment, get_environment
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
    """
    How a standalone run uses its VMs: run everything on the master, create
    one set of workers per job, or keep the workers around for the next job
    """

    CONSUME = "consume"
    CREATE = "create"
    REUSE = "reuse"


def prepare_standalone_clean(backend, load_cache_fn) -> None:
    """
    Loads the stack metadata a previous run persisted on disk, so that clean()
    works even when it is called without an init() in the same process
    """
    if backend.is_initialized():
        load_cache_fn()


def standalone_clean_stop_early(
    backend, stack_data, delete_cache_fn, all_flag
) -> bool:
    """
    Handles the clean() cases that own no cloud resources: consume mode, which
    runs on an instance the user manages, and a stack nothing was created for.
    Returns True when there is nothing else to clean
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
    """States a worker VM reports while it is being set up and used"""

    STARTING = "starting"
    STARTED = "started"
    ERROR = "error"
    INSTALLING = "installing"
    ACTIVE = "active"
    IDLE = "idle"
    BUSY = "busy"
    STOPPED = "stopped"


class JobStatus(Enum):
    """States a job goes through in a standalone run"""

    SUBMITTED = "submitted"
    PENDING = "pending"
    RUNNING = "running"
    DONE = 'done'
    CANCELED = 'canceled'


class LithopsValidationError(Exception):
    """Raised when the setup of a standalone run cannot be trusted"""


def is_container_runtime(runtime_name: str) -> bool:
    """True when the runtime is a container image and not an interpreter"""
    return get_environment(runtime_name) is LocalhostEnvironment.CONTAINER


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

CLOUD_CONFIG_WORKER = r"""
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


def _normalize_package_list(packages) -> List[str]:
    """
    Returns the packages of a config entry as a list, accepting both a list
    and a space separated string
    """
    if not packages:
        return []
    if isinstance(packages, str):
        return [p.strip() for p in packages.split() if p.strip()]
    return [str(p).strip() for p in packages if str(p).strip()]


def _format_apt_packages_for_shell(packages) -> str:
    """
    Returns the apt packages as one argument list for the setup script. The
    names go into a shell command, so anything that is not a package name is
    rejected instead of quoted
    """
    safe = []
    for package in _normalize_package_list(packages):
        if not re.match(r'^[a-z0-9][a-z0-9.+~-]*$', package, re.IGNORECASE):
            raise LithopsValidationError(
                f'Invalid apt package name "{package}" in extra_apt_packages'
            )
        safe.append(package)
    return ' '.join(safe)


def _format_pip_packages_for_shell(packages) -> str:
    """
    Returns the pip specs as one argument list for the setup script. Specs
    carry version markers, so they are quoted rather than restricted, and only
    shell metacharacters are rejected
    """
    quoted = []
    for package in _normalize_package_list(packages):
        if re.search(r'[;&|`$(){}]', package):
            raise LithopsValidationError(
                f'Invalid pip package spec "{package}" in extra_python_packages'
            )
        quoted.append(shlex.quote(package))
    return ' '.join(quoted)


def install_script_kwargs_from_config(config=None) -> Dict[str, str]:
    """
    Returns the arguments get_host_setup_script() takes, read from the
    standalone configuration
    """
    config = config or {}
    return {
        'lithops_pip_spec': lithops_pip_spec_from_config(config),
        'extra_apt_packages': _format_apt_packages_for_shell(
            config.get('extra_apt_packages')
        ),
        'extra_python_packages': _format_pip_packages_for_shell(
            config.get('extra_python_packages')
        ),
    }


def lithops_pip_spec_from_config(config=None, default: str = 'lithops') -> str:
    """
    Returns the pip spec the VMs install, holding only the extras the
    configured backends need. Installing lithops[all] on a VM would pull in
    every cloud SDK, and the redis extra is always needed for the job queue
    """
    if not config:
        return default

    extras = {'redis'}
    lithops_cfg = config.get('lithops') or {}
    for key in ('backend', 'storage'):
        name = (config.get(key) or lithops_cfg.get(key) or '').lower()
        if name.startswith('gcp'):
            extras.add('gcp')
        elif name.startswith('aws'):
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
    docker: bool = True,
    run_install: bool = True,
    lithops_pip_spec: str = 'lithops',
    extra_apt_packages: str = '',
    extra_python_packages: str = '',
) -> str:
    """
    Returns the script that installs everything a Lithops VM host needs.

    Pass run_install=False when the master or worker setup is appended to it,
    as those run the installation themselves. The extra package arguments are
    space separated strings that have already been validated
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
    command -v docker >/dev/null 2>&1 || {{
    export INSTALL_DOCKER=true; export INSTALL_LITHOPS_DEPS=true;
    }};
    command -v unzip >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    command -v pip3 >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};

    if [ "$INSTALL_DOCKER" = true ] && [ "$DOCKER_REQUIRED" = true ]; then
    wait_internet_connection;
    echo "--> Installing Docker repository"
    apt_install update
    apt_install install -y apt-transport-https ca-certificates curl gnupg software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg |
    gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
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


def docker_login(config) -> str:
    """
    Returns the script line that logs into a private container registry, or
    an empty string when no credentials are configured
    """
    backend = config['backend']
    if all(k in config[backend] for k in ("docker_server", "docker_user", "docker_password")):
        user = config[backend]['docker_user']
        passwd = config[backend]['docker_password']
        server = config[backend]['docker_server']
        login = (
            f"printf '%s' {shlex.quote(passwd)} | docker login "
            f"-u {shlex.quote(user)} --password-stdin {shlex.quote(server)}"
        )
        return f"""{login} >> {SA_SETUP_LOG_FILE} 2>&1
    """
    return ""


def get_master_setup_script(config, vm_data) -> str:
    """
    Returns the script that turns a VM into the Lithops master: it unpacks the
    package, starts the master service, and generates the key pair the master
    uses to reach the workers it creates
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
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh/lithops_id_rsa*
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh/id_rsa $USER_HOME/.ssh/id_rsa.pub
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


def _worker_service_commands(config: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Returns the systemd ExecStartPre, ExecStart and ExecStop of the worker
    service. A container runtime runs the worker inside the image, so it has
    to remove a leftover container before starting and after stopping
    """
    if not is_container_runtime(config['runtime']):
        identity = 'id'
        start = f"/usr/bin/python3 {SA_INSTALL_DIR}/worker.py"
        return identity, start, identity

    gpu = '--gpus all ' if config.get('use_gpu') else ''
    uid = os.getuid()
    gid = os.getgid()
    user = os.getenv('USER', 'root')
    runtime = config['runtime']
    rm = '-docker rm -f lithops_worker'
    start = (
        'docker run --rm --name lithops_worker '
        f'{gpu}'
        f'--user {uid}:{gid} '
        f'--env USER={user} --env DOCKER=Lithops '
        f'-p {SA_WORKER_SERVICE_PORT}:{SA_WORKER_SERVICE_PORT} '
        f'-v {SA_INSTALL_DIR}:{SA_INSTALL_DIR} -v /tmp:/tmp '
        f'--entrypoint "python3" {runtime} {SA_INSTALL_DIR}/worker.py'
    )
    return rm, start, rm


def get_worker_setup_script(config, vm_data) -> str:
    """
    Returns the script that turns a VM into a Lithops worker, which only the
    master runs, as it is the one holding the key the worker has to trust
    """
    cmd_pre, cmd_start, cmd_stop = _worker_service_commands(config)
    unit_file = WORKER_SERVICE_FILE.format(cmd_pre, cmd_start, cmd_stop)

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
    echo '{unit_file}' > /etc/systemd/system/{WORKER_SERVICE_NAME};
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
        master_pub_key = ''
        try:
            with open(f'{home_dir}/.ssh/lithops_id_rsa.pub', 'r') as key_file:
                master_pub_key = key_file.read()
        except OSError:
            # The master generates this key on its own setup, so a worker
            # created before that has nothing to authorize yet
            pass

        if master_pub_key:
            script += f"""
        if ! grep -qF "{master_pub_key}" "$USER_HOME/.ssh/authorized_keys"; then
            echo "{master_pub_key}" >> $USER_HOME/.ssh/authorized_keys;
        fi
        """
    return script
