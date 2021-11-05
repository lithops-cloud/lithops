import json

from lithops.constants import (
    STANDALONE_INSTALL_DIR,
    STANDALONE_LOG_FILE,
    STANDALONE_CONFIG_FILE,
)

MASTER_SERVICE_NAME = 'lithops-master.service'
MASTER_SERVICE_FILE = """
[Unit]
Description=Lithops Master Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 {}/master.py
Restart=always

[Install]
WantedBy=multi-user.target
""".format(STANDALONE_INSTALL_DIR)

WORKER_SERVICE_NAME = 'lithops-worker.service'
WORKER_SERVICE_FILE = """
[Unit]
Description=Lithops Worker Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 {}/worker.py
Restart=always

[Install]
WantedBy=multi-user.target
""".format(STANDALONE_INSTALL_DIR)

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

    return """
    wait_internet_connection(){{
    echo "--> Checking internet connection"
    while ! (ping -c 1 -W 1 8.8.8.8| grep -q 'statistics'); do
    echo "Waiting for 8.8.8.8 - network interface might be down..."
    sleep 1
    done;
    }}

    install_packages(){{
    export DOCKER_REQUIRED={2};
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
    apt-get install unzip python3-pip docker-ce docker-ce-cli containerd.io -y --fix-missing;
    else
    apt-get install unzip python3-pip -y --fix-missing;
    fi;

    fi;

    if [[ ! $(pip3 list|grep "lithops") ]]; then
    wait_internet_connection;
    echo "--> Installing Lithops python dependencies"
    pip3 install -U flask gevent lithops boto3;
    fi;
    }}
    install_packages >> {1} 2>&1

    unzip -o /tmp/lithops_standalone.zip -d {0} > /dev/null 2>&1;
    rm /tmp/lithops_standalone.zip
    """.format(STANDALONE_INSTALL_DIR, STANDALONE_LOG_FILE, str(docker).lower())


def get_master_setup_script(config, vm_data):
    """
    Returns master VM installation script
    """
    script = """#!/bin/bash
    mkdir -p /tmp/lithops;
    setup_host(){{
    mv {0}/access.data .;
    rm -R {0};
    mkdir -p {0};
    cp /tmp/lithops_standalone.zip {0};
    mv access.data {0}/access.data;
    echo '{1}' > {0}/access.data;
    echo '{2}' > {0}/config;
    }}
    setup_host >> {3} 2>&1;
    """.format(STANDALONE_INSTALL_DIR, json.dumps(vm_data),
               json.dumps(config), STANDALONE_LOG_FILE)

    script += get_host_setup_script()
    script += """
    setup_service(){{
    echo '{0}' > /etc/systemd/system/{1};
    chmod 644 /etc/systemd/system/{1};
    systemctl daemon-reload;
    systemctl stop {1};
    systemctl enable {1};
    systemctl start {1};
    }}
    setup_service >> {2} 2>&1;

    USER_HOME=$(eval echo ~${{SUDO_USER}});
    test -f $USER_HOME/.ssh/id_rsa || echo '    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null' >> /etc/ssh/ssh_config;
    test -f $USER_HOME/.ssh/id_rsa || ssh-keygen -f $USER_HOME/.ssh/id_rsa -t rsa -N '';
    chown ${{SUDO_USER}}:${{SUDO_USER}} $USER_HOME/.ssh/id_rsa*
    """.format(MASTER_SERVICE_FILE,
               MASTER_SERVICE_NAME,
               STANDALONE_LOG_FILE)
    return script


def get_worker_setup_script(config, vm_data):
    """
    Returns worker VM installation script
    this script is expected to be executed only from Master VM
    """
    ssh_user = vm_data['ssh_credentials']['username']
    home_dir = '/root' if ssh_user == 'root' else f'/home/{ssh_user}'
    try:
        master_pub_key = open(f'{home_dir}/.ssh/id_rsa.pub', 'r').read()
    except Exception:
        master_pub_key = ''

    script = """#!/bin/bash
    rm -R {0}; mkdir -p {0}; mkdir -p /tmp/lithops;
    """.format(STANDALONE_INSTALL_DIR)
    script += get_host_setup_script()
    script += """
    service lithops-master stop;
    echo '{1}' > {2};
    echo '{6}' > {0}/access.data;

    setup_service(){{
    echo '{4}' > /etc/systemd/system/{5};
    chmod 644 /etc/systemd/system/{5};
    systemctl daemon-reload;
    systemctl stop {5};
    systemctl enable {5};
    systemctl start {5};
    }}
    setup_service >> {3} 2>&1
    USER_HOME=$(eval echo ~${{SUDO_USER}});
    echo '{7}' >> $USER_HOME/.ssh/authorized_keys;
    """.format(STANDALONE_INSTALL_DIR, json.dumps(config),
               STANDALONE_CONFIG_FILE, STANDALONE_LOG_FILE,
               WORKER_SERVICE_FILE, WORKER_SERVICE_NAME,
               json.dumps(vm_data), master_pub_key)

    return script
