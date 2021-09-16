import json
from lithops.constants import STANDALONE_INSTALL_DIR, STANDALONE_LOG_FILE,\
    STANDALONE_CONFIG_FILE

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


def get_host_setup_script():
    """
    Returs the script necessary for installing a lithops VM host
    """
    return """
    install_packages(){{
    command -v unzip >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    command -v pip3 >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    command -v docker >/dev/null 2>&1 || {{ export INSTALL_LITHOPS_DEPS=true; }};
    if [ "$INSTALL_LITHOPS_DEPS" = true ] ; then
    rm /var/lib/apt/lists/* -vfR;
    apt-get clean;
    apt-get update;
    apt-get install apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y;
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -;
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable";
    apt-get update;
    apt-get install unzip redis-server python3-pip docker-ce docker-ce-cli containerd.io -y;
    pip3 install -U flask gevent lithops;
    fi;
    }}
    install_packages >> {1} 2>&1

    unzip -o /tmp/lithops_standalone.zip -d {0} > /dev/null 2>&1;
    rm /tmp/lithops_standalone.zip
    """.format(STANDALONE_INSTALL_DIR, STANDALONE_LOG_FILE)


def get_master_setup_script(config, vm_data):
    """
    Returns master VM installation script
    """
    script = """
    mkdir -p /tmp/lithops;
    setup_host(){{
    mv {0}/access.data .;
    rm -R {0};
    mkdir -p {0};
    cp /tmp/lithops_standalone.zip {0};
    mv access.data {0}/access.data;
    test -f {0}/access.data || echo '{1}' > {0}/access.data;
    test -f {0}/config || echo '{2}' > {0}/config;
    mv /tmp/*.py '{0}';
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
    setup_service >> {2} 2>&1
    """.format(MASTER_SERVICE_FILE,
               MASTER_SERVICE_NAME,
               STANDALONE_LOG_FILE)
    return script


def get_worker_setup_script(config, vm_data):
    """
    Returns worker VM installation script
    """
    script = """
    rm -R {0}; mkdir -p {0}; mkdir -p /tmp/lithops;
    """.format(STANDALONE_INSTALL_DIR)
    script += get_host_setup_script()
    script += """
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
    """.format(STANDALONE_INSTALL_DIR, json.dumps(config),
               STANDALONE_CONFIG_FILE, STANDALONE_LOG_FILE,
               WORKER_SERVICE_FILE, WORKER_SERVICE_NAME,
               json.dumps(vm_data))
    return script
