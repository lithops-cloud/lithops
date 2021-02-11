import sys
import logging
import subprocess as sp


SA_LOG_FILE = '/tmp/lithops/standalone.log'
LOGGER_FORMAT = "%(asctime)s [%(levelname)s] %(name)s -- %(message)s"
STANDALONE_INSTALL_DIR = '/opt/lithops'

CONTROLLER_SERVICE_NAME = 'lithopscontroller.service'
CONTROLLER_SERVICE_FILE = """
[Unit]
Description=Lithops Controller
After=network.target

[Service]
ExecStart=/usr/bin/python3 {}/master_controller.py
Restart=always

[Install]
WantedBy=multi-user.target
""".format(STANDALONE_INSTALL_DIR)

logging.basicConfig(filename=SA_LOG_FILE, level=logging.INFO,
                    format=LOGGER_FORMAT)
logger = logging.getLogger('master_setup')


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
    apt-get install unzip python3-pip docker-ce docker-ce-cli containerd.io -y;
    pip3 install -U flask gevent lithops;
    fi;
    unzip -o /tmp/lithops_standalone.zip -d {0} > /dev/null 2>&1;
    }}
    install_packages >> {1} 2>&1
    """.format(STANDALONE_INSTALL_DIR, SA_LOG_FILE)


def setup_master():
    """
    Setup master VM
    """
    logger.info('Installing dependencies')
    script = get_host_setup_script()

    with open(SA_LOG_FILE, 'a') as log_file:
        sp.run(script, shell=True, check=True, stdout=log_file,
               stderr=log_file, universal_newlines=True)

    script = """
    setup_service(){{
    echo '{0}' > /etc/systemd/system/{1};
    chmod 644 /etc/systemd/system/{1};
    systemctl daemon-reload;
    systemctl stop {1};
    systemctl enable {1};
    systemctl start {1};
    }}
    setup_service >> {2} 2>&1
    """.format(CONTROLLER_SERVICE_FILE,
               CONTROLLER_SERVICE_NAME,
               SA_LOG_FILE)

    logger.info('Installing controller service')
    with open(SA_LOG_FILE, 'a') as log_file:
        sp.run(script, shell=True, check=True, stdout=log_file,
               stderr=log_file, universal_newlines=True)

    logger.info('Master VM installation process finished')


if __name__ == "__main__":
    logger.info('Starting Lithops Master VM setup script')

    with open(SA_LOG_FILE, 'a') as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        setup_master()
