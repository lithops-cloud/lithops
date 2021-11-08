import logging
import time

from lithops.constants import COMPUTE_CLI_MSG
from lithops.util.ssh_client import SSHClient

logger = logging.getLogger(__name__)


INSTANCE_START_TIMEOUT = 30


class VMBackend:

    def __init__(self, vm_config, mode):
        logger.debug("Creating Virtual Machine client")
        self.name = 'vm'
        self.config = vm_config
        self.mode = mode
        self.master = None

        msg = COMPUTE_CLI_MSG.format('Virtual Machine')
        logger.info("{}".format(msg))

    def init(self):
        """
        Initialize the VM backend
        """
        if self.mode == 'consume':
            logger.debug('Initializing VM backend (Consume mode)')
            self.master = VMInstance(self.config)
        else:
            raise Exception(f'{self.mode} mode is not allowed in the VM backend')

    def clean(self, **kwargs):
        pass

    def clear(self, **kwargs):
        pass

    def dismantle(self, **kwargs):
        pass

    def get_runtime_key(self, runtime_name):
        runtime = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = '/'.join([self.name, self.config['ip_address'], runtime])
        return runtime_key


class VMInstance:

    def __init__(self, config):
        self.public_ip = self.private_ip = self.config['ip_address']
        self.ssh_client = None
        self.ssh_credentials = {
            'username': self.config.get('ssh_user', 'root'),
            'password': self.config.get('ssh_password', None),
            'key_filename': self.config.get('ssh_key_filename', None)
        }
        logger.debug('{} created'.format(self))

    def __str__(self):
        return 'VM instance {}'.format(self.ip_address)

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM only if the Instance is the master
        """
        if self.public_ip:
            if not self.ssh_client:
                self.ssh_client = SSHClient(self.public_ip, self.ssh_credentials)
        return self.ssh_client

    def del_ssh_client(self):
        """
        Deletes the ssh client
        """
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None

    def is_ready(self, verbose=False):
        """
        Checks if the VM is ready to receive ssh connections
        """
        try:
            self.get_ssh_client().run_remote_command('id')
        except Exception as e:
            if verbose:
                logger.debug(f'ssh to {self.private_ip} failed: {e}')
            self.del_ssh_client()
            return False
        return True

    def wait_ready(self, verbose=False):
        """
        Waits until the VM is ready to receive ssh connections
        """
        logger.debug(f'Waiting {self} to become ready')

        start = time.time()
        while(time.time() - start < INSTANCE_START_TIMEOUT):
            if self.is_ready(verbose=verbose):
                start_time = round(time.time()-start, 2)
                logger.debug(f'{self} ready in {start_time} seconds')
                return True
            time.sleep(5)

        raise TimeoutError(f'Readiness probe expired on {self}')

    def get_public_ip(self):
        """
        Requests the the primary public IP address
        """
        return self.public_ip

    def create(self, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def delete(self):
        pass
