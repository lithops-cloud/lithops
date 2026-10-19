#
# Copyright IBM Coorp. 2021
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import logging
import time

from lithops.standalone.utils import StandaloneMode
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR
from lithops.util.ssh_client import SSHClient, ssh_boot_status_message
from lithops.standalone import LithopsValidationError

logger = logging.getLogger(__name__)


INSTANCE_START_TIMEOUT = 30


class VMBackend:

    def __init__(self, vm_config, mode):
        logger.debug("Creating Virtual Machine client")
        self.name = 'vm'
        self.config = vm_config
        self.mode = mode
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.master = None

        logger.info(COMPUTE_CLI_MSG.format('Virtual Machine'))

    def is_initialized(self):
        """
        Checks if the backend is initialized
        """
        return self.mode == StandaloneMode.CONSUME.value

    def init(self):
        """
        Initialize the VM backend
        """
        if self.mode == 'consume':
            logger.debug('Initializing VM backend (Consume mode)')
            self.master = VMInstance(self.config)
        else:
            raise Exception(f'{self.mode} mode is not allowed in the VM backend')

    def build_image(self, **kwargs):
        pass

    def list_images(self, **kwargs):
        pass

    def clean(self, **kwargs):
        pass

    def clear(self, job_keys=None):
        pass

    def dismantle(self, **kwargs):
        pass

    def get_instance(self, name, **kwargs):
        """
        Returns a VM class instance, which is how the master and its budget
        keeper get hold of the VM they run on
        """
        instance = VMInstance(self.config)
        instance.name = name

        for key in kwargs:
            if hasattr(instance, key) and kwargs[key] is not None:
                setattr(instance, key, kwargs[key])

        return instance

    def get_worker_instance_type(self):
        return None

    def get_runtime_key(self, runtime_name, version=__version__):
        runtime = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = os.path.join(self.name, version, self.config['ip_address'], runtime)
        return runtime_key


class VMInstance:

    def __init__(self, config):
        self.config = config
        self.name = 'lithops-consume'
        self.instance_id = '0af1'
        # Stored in redis by the master, which cannot store None
        self.instance_type = 'VM'
        # Lithops never created this machine, so it never deletes it
        self.delete_on_dismantle = False
        self.public_ip = self.private_ip = self.config['ip_address']
        self.ssh_client = None

        ssh_user = self.config['ssh_username']
        self.home_dir = '/root' if ssh_user == 'root' else f'/home/{ssh_user}'
        self.ssh_credentials = {
            'username': ssh_user,
            'password': self.config.get('ssh_password', None),
            'key_filename': self.config.get('ssh_key_filename', '~/.ssh/id_rsa')
        }

        logger.debug(f'{self} created')

    def __str__(self):
        return f'VM instance {self.public_ip}'

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM only if the Instance is the master
        """
        if self.public_ip and not self.ssh_client:
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

    def is_ready(self):
        """
        Checks if the VM is ready to receive ssh connections
        """
        try:
            self.get_ssh_client().run_remote_command('id')
        except LithopsValidationError as e:
            raise e
        except Exception as e:
            logger.debug(f'SSH to {self.public_ip}: {ssh_boot_status_message(e)}')
            self.del_ssh_client()
            return False
        return True

    def wait_ready(self, timeout=INSTANCE_START_TIMEOUT):
        """
        Waits until the VM is ready to receive ssh connections
        """
        logger.debug(f'Waiting {self} to become ready')

        start = time.time()
        while (time.time() - start < timeout):
            if self.is_ready():
                start_time = round(time.time() - start, 2)
                logger.debug(f'{self} ready in {start_time} seconds')
                return True
            time.sleep(5)

        raise TimeoutError(f'Readiness probe expired on {self}')

    def get_instance_data(self):
        """
        Returns the instance information
        """
        return {'id': self.instance_id, 'public_ip': self.public_ip}

    def get_instance_id(self):
        """
        Requests the Instance ID
        """
        return self.instance_id

    def get_public_ip(self):
        """
        Requests the primary public IP address
        """
        return self.public_ip

    def get_private_ip(self):
        """
        Requests the primary private IP address
        """
        return self.private_ip

    def create(self, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def delete(self):
        pass
