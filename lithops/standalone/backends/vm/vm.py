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

        msg = COMPUTE_CLI_MSG.format('Virtual Machine')
        logger.info("{} - Host: {}".format(msg, self.host))

    def get_ssh_credentials(self):
        return self.ssh_credentials

    def get_ip_address(self):
        return self.host

    def start(self):
        pass

    def stop(self):
        pass

    def get_runtime_key(self, runtime_name):
        runtime_key = os.path.join(self.name, self.host,
                                   runtime_name.strip("/"))

        return runtime_key
