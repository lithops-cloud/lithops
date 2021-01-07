import os
import logging
from lithops.constants import COMPUTE_CLI_MSG

logger = logging.getLogger(__name__)


class VMClient:

    def __init__(self, config):
        logger.debug("Creating Virtual Machine client")
        self.config = config

        self.host = self.config.get('host')
        self.ssh_credentials = {'username': self.config.get('ssh_user', 'root'),
                                'password': self.config.get('ssh_password', None),
                                'key_filename': self.config.get('ssh_key_filename', None)}

        from lithops.util.ssh_client import SSHClient
        self.ssh_client = SSHClient(self.ssh_credentials)

        msg = COMPUTE_CLI_MSG.format('Virtual Machine')
        logger.info("{} - Host: {}".format(msg, self.host))

    def get_ssh_credentials(self):
        return self.ssh_credentials

    def get_ssh_client(self):
        return self.ssh_client

    def get_ip_address(self):
        return self.host

    def set_instance_id(self, instance_id):
        self.instance_id = instance_id

    def set_ip_address(self, ip_address):
        self.ip_address = ip_address

    def is_custom_image(self):
        return False

    def start(self):
        pass

    def stop(self):
        pass

    def get_runtime_key(self, runtime_name):
        runtime_key = os.path.join(self.name, self.host,
                                   runtime_name.strip("/"))

        return runtime_key

    def is_ready(self):
        """
        Checks if the VM instance is ready to receive ssh connections
        """
        logger.debug("Check if {} ready".format(self.host))
        try:
            out = self.ssh_client().run_remote_command(self.host, 'id', timeout=2)
        except Exception as e:
            logger.warning(e)
            return False
        logger.debug("Backend {} is running".format(self.host))
        return True
