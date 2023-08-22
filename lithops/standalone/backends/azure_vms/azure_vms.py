#
# Copyright IBM Corp. 2023
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
import re
import time
import uuid
import logging
import base64
from concurrent.futures import ThreadPoolExecutor
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.core.exceptions import ResourceNotFoundError

from lithops.version import __version__
from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR, SA_DATA_FILE
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import ExecMode
from lithops.standalone.standalone import LithopsValidationError


logger = logging.getLogger(__name__)

INSTANCE_START_TIMEOUT = 180
DEFAULT_UBUNTU_IMAGE = 'Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest'


def b64s(string):
    """
    Base-64 encode a string and return a string
    """
    return base64.b64encode(string.encode('utf-8')).decode('ascii')


class AzureVMSBackend:

    def __init__(self, config, mode):
        logger.debug("Creating Azure Virtual Machines client")
        self.name = 'azure_vms'
        self.config = config
        self.mode = mode
        self.location = config['region']
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, self.location + '_data')
        self.vnet_data_type = 'provided' if 'vnet_name' in self.config else 'created'
        self.ssh_data_type = 'provided' if 'ssh_key_filename' in config else 'created'

        self.azure_data = None
        self.vnet_name = None
        self.vnet_key = None

        credential = DefaultAzureCredential()
        subscription_id = self.config['subscription_id']
        self.compute_client = ComputeManagementClient(credential, subscription_id)
        self.network_client = NetworkManagementClient(credential, subscription_id)

        self.master = None
        self.workers = []

        msg = COMPUTE_CLI_MSG.format('Azure Virtual Machines')
        logger.info(f"{msg} - Region: {self.location}")

    def _load_azure_vms_data(self):
        """
        Loads Azure data from local cache
        """
        self.azure_data = load_yaml_config(self.cache_file)

        if self.azure_data:
            logger.debug(f'Azure VMs data loaded from {self.cache_file}')

        if 'vnet_name' in self.azure_data:
            self.vnet_key = self.azure_data['vnet_id'][-6:]
            self.vnet_name = self.azure_data['vnet_name']

    def _dump_azure_vms_data(self):
        """
        Dumps Azure data to local cache
        """
        dump_yaml_config(self.cache_file, self.azure_data)

    def _create_vnet(self):
        """
        Creates a new Virtual Network
        """
        if 'vnet_name' in self.config:
            return

        if 'vnet_name' in self.azure_data:
            vnets_info = list(self.network_client.virtual_networks.list(self.config['resource_group']))
            for vnet in vnets_info:
                if vnet.name == self.vnet_name:
                    self.config['vnet_id'] = vnet.id
                    self.config['vnet_name'] = vnet.name
                    return

        self.vnet_name = self.config.get('vnet_name', f'lithops-vnet-{str(uuid.uuid4())[-6:]}')
        logger.debug(f'Setting virtual network name to: {self.vnet_name}')

        assert re.match("^[a-z0-9-:-]*$", self.vnet_name),\
            f'Virtual network name "{self.vnet_name}" not valid'

        vnets_info = list(self.network_client.virtual_networks.list(self.config['resource_group']))
        for vnet in vnets_info:
            if vnet.name == self.vnet_name:
                self.config['vnet_id'] = vnet.id
                self.config['vnet_name'] = vnet.name
                break

        if 'vnet_name' not in self.config:
            logger.debug(f'Creating virtual network {self.vnet_name}')

            # Provision the virtual network and wait for completion
            poller = self.network_client.virtual_networks.begin_create_or_update(
                self.config['resource_group'],
                self.vnet_name,
                {
                    "location": self.location,
                    "address_space": {"address_prefixes": ["10.0.0.0/16"]},
                },
            )
            vnet_result = poller.result()
            logger.debug(
                f"Provisioned virtual network {vnet_result.name} with address prefixes {vnet_result.address_space.address_prefixes}"
            )
            self.config['vnet_id'] = vnet_result.id
            self.config['vnet_name'] = vnet_result.name

    def _create_subnet(self):
        """
        Creates a new subnet
        """
        if 'subnet_name' in self.config:
            return

        if 'subnet_name' in self.azure_data:
            subnets_info = list(self.network_client.subnets.list(self.config['resource_group'], self.vnet_name))
            for subnet in subnets_info:
                if subnet.name == self.azure_data['subnet_name']:
                    self.config['subnet_id'] = subnet.id
                    self.config['subnet_name'] = subnet.name
                    return

        self.subnet_name = self.vnet_name + '-subnet'

        subnets_info = list(self.network_client.subnets.list(self.config['resource_group'], self.vnet_name))
        for subnet in subnets_info:
            if subnet.name == self.azure_data['subnet_name']:
                self.config['subnet_id'] = subnet.id
                self.config['subnet_name'] = subnet.name

        if 'subnet_name' not in self.config:
            poller = self.network_client.subnets.begin_create_or_update(
                self.config['resource_group'],
                self.vnet_name,
                self.subnet_name,
                {"address_prefix": "10.0.0.0/24"},
            )
            subnet_result = poller.result()

            logger.debug(
                f"Provisioned virtual subnet {subnet_result.name} with address prefix {subnet_result.address_prefix}"
            )
            self.config['subnet_id'] = subnet_result.id
            self.config['subnet_name'] = subnet_result.name

    def _create_security_group(self):
        """
        Creates a new Security group
        """
        if 'security_group_id' in self.config:
            return

        if 'security_group_id' in self.azure_data:
            try:
                sg_info = self.network_client.network_security_groups.get(
                    self.config['resource_group'], self.azure_data['security_group_name']
                )
                self.config['security_group_id'] = sg_info.id
                self.config['security_group_name'] = sg_info.name
                return
            except ResourceNotFoundError:
                pass

        security_group_name = 'lithops-security-group'

        try:
            sg_info = self.network_client.network_security_groups.get(
                self.config['resource_group'], security_group_name
            )
            self.config['security_group_id'] = sg_info.id
            self.config['security_group_name'] = sg_info.name
        except ResourceNotFoundError:
            pass

        if 'security_group_id' not in self.config:
            nsg_rule = {
                "name": "allow-ssh",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "*",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "direction": "Inbound",
                "priority": 100
            }

            # Define the network security group to contain the rule
            network_security_group = {
                "location": self.location,
                "securityRules": [nsg_rule]
            }

            # Create or update the network security group
            poller = self.network_client.network_security_groups.begin_create_or_update(
                self.config['resource_group'],
                security_group_name,
                network_security_group
            )
            sg_result = poller.result()

            self.config['security_group_name'] = sg_result.name
            self.config['security_group_id'] = sg_result.id

    def _create_master_floating_ip(self):
        """
        Creates the master VM floating IP address
        """

        def get_floating_ip(fip_name):
            try:
                fip_info = self.network_client.network_security_groups.get(
                    self.config['resource_group'], fip_name
                )
                self.config['floating_ip'] = fip_info.ip_address
                self.config['floating_ip_name'] = fip_info.name
                self.config['floating_ip_id'] = fip_info.id
            except ResourceNotFoundError:
                pass

        if 'floating_ip_id' in self.azure_data:
            get_floating_ip(self.azure_data['floating_ip_name'])

        floating_ip_name = self.vnet_name + '-ip'

        if 'floating_ip_id' not in self.config:
            get_floating_ip(floating_ip_name)

        if 'floating_ip_id' not in self.config:
            poller = self.network_client.public_ip_addresses.begin_create_or_update(
                self.config['resource_group'],
                floating_ip_name,
                {
                    "location": self.location,
                    "sku": {"name": "Standard"},
                    "public_ip_allocation_method": "Static",
                    "public_ip_address_version": "IPV4",
                },
            )
            ip_address_result = poller.result()
            logger.debug(f"Provisioned public IP address {ip_address_result.ip_address}")
            self.config['floating_ip'] = ip_address_result.ip_address
            self.config['floating_ip_name'] = ip_address_result.name
            self.config['floating_ip_id'] = ip_address_result.id

    def _create_ssh_key(self):
        """
        Creates a new ssh key pair
        """
        if 'ssh_key_filename' in self.config:
            return

        if 'ssh_key_filename' in self.azure_data:
            if os.path.isfile(self.azure_data['ssh_key_filename']):
                self.config['ssh_key_filename'] = self.azure_data['ssh_key_filename']
                return

        keyname = f'lithops-key-{str(uuid.uuid4())[-8:]}'
        filename = os.path.join("~", ".ssh", f"{keyname}.{self.name}.id_rsa")
        key_filename = os.path.expanduser(filename)

        if not os.path.isfile(key_filename):
            logger.debug("Generating new ssh key pair")
            os.system(f'ssh-keygen -b 2048 -t rsa -f {key_filename} -q -N ""')
            logger.debug(f"SHH key pair generated: {key_filename}")

        self.config['ssh_key_filename'] = key_filename

    def _create_master_instance(self):
        """
        Creates the master VM insatnce
        """
        name = self.config.get('master_name') or f'lithops-master-{self.vnet_key}'
        self.master = VMInstance(name, self.config, self.compute_client, public=True)
        self.master.name = self.config['instance_name'] if self.mode == ExecMode.CONSUME.value else name
        self.master.public_ip = self.config['floating_ip']
        self.master.instance_type = self.config['master_instance_type']
        self.master.delete_on_dismantle = False
        self.master.ssh_credentials.pop('password')
        self.master.get_instance_data()
        self.config['instance_id'] = self.master.instance_id

    def init(self):
        """
        Initialize the backend by defining the Master VM
        """
        logger.debug(f'Initializing Azure Virtual Machines backend ({self.mode} mode)')

        self._load_azure_vms_data()
        if self.mode != self.azure_data.get('mode'):
            self.azure_data = {}

        if self.mode == ExecMode.CONSUME.value:
            instance_name = self.config['instance_name']
            if not self.azure_data or instance_name != self.azure_data.get('instance_name'):
                try:
                    self.compute_client.virtual_machines.get(
                        self.config['resource_group'], instance_name
                    )
                except ResourceNotFoundError:
                    raise Exception(f"VM Instance {instance_name} does not exists")

            # Create the master VM instance
            self._create_master_instance()

            # Make sure that the ssh key is provided
            self.config['ssh_key_filename'] = self.config.get('ssh_key_filename', '~/.ssh/id_rsa')

            self.azure_data = {
                'mode': self.mode,
                'vnet_data_type': 'provided',
                'ssh_data_type': 'provided',
                'instance_name': self.config['instance_name'],
                'master_id': self.config['instance_id'],
                'ssh_key_filename': self.config['ssh_key_filename'],
            }

        elif self.mode in [ExecMode.CREATE.value, ExecMode.REUSE.value]:

            # Create the Virtual Netowrk if not exists
            self._create_vnet()

            # Set the suffix used for the VNET resources
            self.vnet_key = self.config['vnet_id'][-6:]

            # Create the Subnet if not exists
            self._create_subnet()
            # Create the security group if not exists
            self._create_security_group()
            # Create the master VM floating IP address
            self._create_master_floating_ip()
            # Create the ssh key pair if not exists
            self._create_ssh_key()

            # Create the master VM instance
            self._create_master_instance()

            self.azure_data = {
                'mode': self.mode,
                'vnet_data_type': self.vnet_data_type,
                'ssh_data_type': self.ssh_data_type,
                'master_name': self.master.name,
                'master_id': self.vnet_key,
                'vnet_name': self.config['vnet_name'],
                'vnet_id': self.config['vnet_id'],
                'subnet_name': self.config['subnet_name'],
                'subnet_id': self.config['subnet_id'],
                'ssh_key_filename': self.config['ssh_key_filename'],
                'security_group_id': self.config['security_group_id'],
                'security_group_name': self.config['security_group_name'],
                'floating_ip_id': self.config['floating_ip_id'],
                'floating_ip_name': self.config['floating_ip_name']
            }

        self._dump_azure_vms_data()

    def build_image(self, image_name, script_file, overwrite, extra_args=[]):
        """
        Builds a new VM Image
        """
        raise NotImplementedError()

    def list_images(self):
        """
        List VM Images
        """

        images_def = self.compute_client.virtual_machine_images.list_offers(
            location=self.location,
            publisher_name='Canonical'
        )

        images_user = self.compute_client.images.list_by_resource_group(
            self.config['resource_group']
        )

        images_def.extend(images_user)

        result = set()

        for image in images_def:
            result.add((image.name, image.id, "Unknown"))

        return sorted(result, key=lambda x: x[2], reverse=True)

    def _delete_vm_instances(self, all=False):
        """
        Deletes all worker VM instances
        """
        msg = (f"Deleting Lithops VMs from {self.azure_data['vnet_name']}")
        logger.info(msg)

        vms_prefixes = ('lithops-worker', 'lithops-master') if all else ('lithops-worker',)

        instances_to_delete = []
        vms_info = self.compute_client.virtual_machines.list(self.config['resource_group'])
        for vm in vms_info:
            if 'type' in vm.tags and vm.tags['type'] == 'lithops-runtime' \
               and vm.name.startswith(vms_prefixes) and vm.tags['lithops_vnet'] == self.vnet_name:
                instances_to_delete.append(vm)

        def delete_instance(instance):
            logger.debug(f"Deleting VM instance {instance.name}")

            poller = self.compute_client.virtual_machines.begin_delete(
                self.config['resource_group'], instance.name, force_deletion=True
            )
            poller.result()

            nic_name = instance.network_profile.network_interfaces[0].id.split('/')[-1]
            poller = self.network_client.network_interfaces.begin_delete(
                self.config['resource_group'], nic_name
            )
            poller.result()

            disk_name = instance.storage_profile.os_disk.name
            poller = self.compute_client.disks.begin_delete(
                self.config['resource_group'], disk_name
            )
            poller.result()

        if len(instances_to_delete) > 0:
            with ThreadPoolExecutor(len(instances_to_delete)) as executor:
                futures = [executor.submit(delete_instance, i) for i in instances_to_delete]
                [fut.result() for fut in futures]

        master_pk = os.path.join(self.cache_dir, f"{self.azure_data['master_name']}-id_rsa.pub")
        if os.path.isfile(master_pk):
            os.remove(master_pk)

        if self.azure_data['vnet_data_type'] == 'provided':
            return

    def _delete_vnet_and_subnet(self):
        """
        Deletes all the Azure VMs resources
        """
        if self.azure_data['vnet_data_type'] == 'provided':
            return

        try:
            logger.debug(f"Deleting Subnet {self.azure_data['subnet_name']}")
            poller = self.network_client.subnets.begin_delete(
                self.config['resource_group'],
                self.azure_data['vnet_name'],
                self.azure_data['subnet_name']
            )
            poller.result()
        except ResourceNotFoundError:
            pass

        try:
            logger.debug(f"Deleting Virtual Network {self.azure_data['vnet_name']}")
            poller = self.network_client.virtual_networks.begin_delete(
                self.config['resource_group'],
                self.azure_data['vnet_name']
            )
            poller.result()
        except ResourceNotFoundError:
            pass

        try:
            logger.debug(f"Deleting Public IP address {self.azure_data['floating_ip_name']}")
            poller = self.network_client.public_ip_addresses.begin_delete(
                self.config['resource_group'],
                self.azure_data['floating_ip_name']
            )
            poller.result()
        except ResourceNotFoundError:
            pass

    def _delete_ssh_key(self):
        """
        Deletes the ssh key
        """
        if self.azure_data['ssh_data_type'] == 'provided':
            return

        key_filename = self.azure_data['ssh_key_filename']
        if "lithops-key-" in key_filename:
            if os.path.isfile(key_filename):
                os.remove(key_filename)
            if os.path.isfile(f"{key_filename}.pub"):
                os.remove(f"{key_filename}.pub")

    def clean(self, all=False):
        """
        Clean all the VPC resources
        """
        logger.info('Cleaning Azure Virtual Machines resources')

        self._load_azure_vms_data()

        if not self.azure_data:
            return

        if self.azure_data['mode'] == ExecMode.CONSUME.value:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        else:
            self._delete_vm_instances(all=all)
            self._delete_vnet_and_subnet() if all else None
            self._delete_ssh_key() if all else None
            if all and os.path.exists(self.cache_file):
                os.remove(self.cache_file)

    def clear(self, job_keys=None):
        """
        Delete all the workers
        """
        # clear() is automatically called after get_result(),
        self.dismantle(include_master=False)

    def dismantle(self, include_master=True):
        """
        Stop all worker VM instances
        """
        if len(self.workers) > 0:
            with ThreadPoolExecutor(len(self.workers)) as ex:
                ex.map(lambda worker: worker.stop(), self.workers)
            self.workers = []

        if include_master or self.mode == ExecMode.CONSUME.value:
            # in consume mode master VM is a worker
            self.master.stop()

    def get_instance(self, name, **kwargs):
        """
        Returns a VM class instance.
        Does not creates nor starts a VM instance
        """
        instance = VMInstance(name, self.config, self.compute_client)

        for key in kwargs:
            if hasattr(instance, key):
                setattr(instance, key, kwargs[key])

        return instance

    def create_worker(self, name):
        """
        Creates a new worker VM instance
        """
        worker = VMInstance(name, self.config, self.compute_client, public=False)
        ssh_key = f'{self.cache_dir}/{self.master.name}-id_rsa'
        worker.ssh_credentials['key_filename'] = ssh_key
        worker.ssh_credentials.pop('password')
        worker.create()
        worker.ssh_credentials['key_filename'] = '~/.ssh/id_rsa'
        self.workers.append(worker)

    def get_runtime_key(self, runtime_name, version=__version__):
        """
        Creates the runtime key
        """
        name = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = os.path.join(self.name, version, self.azure_data['master_id'], name)
        return runtime_key


class VMInstance:

    def __init__(self, name, config, compute_client=None, public=False):
        """
        Initialize a VM instance
        VMs can have master role, this means they will have a public IP address
        """
        self.name = name.lower()
        self.config = config

        self.delete_on_dismantle = self.config['delete_on_dismantle']
        self.instance_type = self.config['worker_instance_type']
        self.location = self.config['region']
        self.spot_instance = self.config['request_spot_instances']

        self.compute_client = compute_client
        self.public = public

        self.ssh_client = None
        self.instance_id = None
        self.instance_data = None
        self.private_ip = None
        self.public_ip = '0.0.0.0'
        self.home_dir = '/home/ubuntu'

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', '~/.ssh/id_rsa')
        }

        self.create_client()

    def __str__(self):
        ip = self.public_ip if self.public else self.private_ip

        if ip is None or ip == '0.0.0.0':
            return f'VM instance {self.name}'
        else:
            return f'VM instance {self.name} ({ip})'

    def create_client(self):
        """
        Creates an Azure compute client
        """
        # Acquire a credential object using CLI-based authentication.
        credential = DefaultAzureCredential()
        subscription_id = self.config['subscription_id']
        self.compute_client = ComputeManagementClient(credential, subscription_id)
        self.network_client = NetworkManagementClient(credential, subscription_id)

        return self.compute_client

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM
        """
        if self.public:
            if not self.ssh_client or self.ssh_client.ip_address != self.public_ip:
                self.ssh_client = SSHClient(self.public_ip, self.ssh_credentials)
        else:
            if not self.ssh_client or self.ssh_client.ip_address != self.private_ip:
                self.ssh_client = SSHClient(self.private_ip, self.ssh_credentials)

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
        Checks if the VM instance is ready to receive ssh connections
        """
        login_type = 'password' if 'password' in self.ssh_credentials and \
            not self.public else 'publickey'
        try:
            self.get_ssh_client().run_remote_command('id')
        except LithopsValidationError as err:
            raise err
        except Exception as err:
            logger.debug(f'SSH to {self.public_ip if self.public else self.private_ip} failed ({login_type}): {err}')
            self.del_ssh_client()
            return False
        return True

    def wait_ready(self, timeout=INSTANCE_START_TIMEOUT):
        """
        Waits until the VM instance is ready to receive ssh connections
        """
        logger.debug(f'Waiting {self} to become ready')

        start = time.time()

        self.get_public_ip() if self.public else self.get_private_ip()

        while (time.time() - start < timeout):
            if self.is_ready():
                start_time = round(time.time() - start, 2)
                logger.debug(f'{self} ready in {start_time} seconds')
                return True
            time.sleep(5)

        raise TimeoutError(f'Readiness probe expired on {self}')

    def _create_instance(self, user_data=None):
        """
        Creates a new VM instance
        """
        logger.debug(f"Creating new VM instance {self.name}")

        # Create NIC
        nic_params = {
            'location': self.location,
            'ip_configurations': [{
                'name': 'ipconfig1',
                'subnet': {'id': self.config['subnet_id']},
            }],
            "network_security_group": {"id": self.config['security_group_id']}
        }

        if self.public and not self.public_ip:
            poller = self.network_client.public_ip_addresses.begin_create_or_update(
                self.config['resource_group'],
                self.name + '-ip',
                {
                    "location": self.location,
                    "sku": {"name": "Standard"},
                    "public_ip_allocation_method": "Static",
                    "public_ip_address_version": "IPV4",
                },
            )
            ip_address_result = poller.result()
            self.public_ip = ip_address_result.ip_address
            logger.debug(f"Provisioned public IP address {self.public_ip}")
            nic_params['ip_configurations'][0]['public_ip_address'] = {"id": ip_address_result.id}

        elif self.public:
            nic_params['ip_configurations'][0]['public_ip_address'] = {"id": self.config['floating_ip_id']}

        poller = self.network_client.network_interfaces.begin_create_or_update(
            self.config['resource_group'],
            self.name + '-nic',
            nic_params
        )
        nic_data = poller.result()
        self.private_ip = nic_data.ip_configurations[0].private_ip_address

        # Create VM
        vm_username = self.ssh_credentials['username']
        with open(self.ssh_credentials['key_filename'] + '.pub', 'r') as pk:
            vm_pk_data = pk.read().strip()

        vm_parameters = {
            'location': self.location,
            'tags': {
                'type': 'lithops-runtime',
                'lithops_version': str(__version__),
                'lithops_vnet': self.config['vnet_name']
            },
            'os_profile': {
                'computer_name': self.name,
                'admin_username': vm_username,
                'linux_configuration': {
                    'disable_password_authentication': True,
                    "ssh": {
                        "public_keys": [
                            {
                                "path": f"/home/{vm_username}/.ssh/authorized_keys",
                                "key_data": vm_pk_data
                            }
                        ]
                    }
                },
            },
            'hardware_profile': {
                'vm_size': self.instance_type
            },
            'storage_profile': {
                'image_reference': {
                    'publisher': DEFAULT_UBUNTU_IMAGE.split(':')[0],
                    'offer': DEFAULT_UBUNTU_IMAGE.split(':')[1],
                    'sku': DEFAULT_UBUNTU_IMAGE.split(':')[2],
                    'version': DEFAULT_UBUNTU_IMAGE.split(':')[3]
                },
                'osDisk': {
                    'name': self.name + '-osdisk',
                    'createOption': 'fromImage',
                    'managedDisk': {
                        'storageAccountType': 'Standard_LRS'
                    }
                }
            },
            'network_profile': {
                'network_interfaces': [{
                    'id': nic_data.id,
                    'properties': {
                        'primary': True
                    }
                }]
            }
        }

        if 'image_id' in self.config:
            vm_parameters['storage_profile']['image_reference'] = {"id": self.config['image_id']}

        poller = self.compute_client.virtual_machines.begin_create_or_update(
            self.config['resource_group'],
            self.name,
            vm_parameters
        )

        return self.instance_data

    def get_instance_data(self):
        """
        Returns the instance information
        """
        if self.instance_data:
            return self.instance_data

        try:
            instance_data = self.compute_client.virtual_machines.get(
                self.config['resource_group'], self.name
            )
        except ResourceNotFoundError:
            instance_data = None

        if instance_data and instance_data.provisioning_state == 'Succeeded':
            self.instance_data = instance_data
            self.instance_id = instance_data.vm_id
            nic_id = instance_data.network_profile.network_interfaces[0].id
            nic_data = self.network_client.network_interfaces.get(
                self.config['resource_group'], nic_id.split('/')[-1]
            )
            ip_config = nic_data.ip_configurations[0]
            self.private_ip = ip_config.private_ip_address
            if ip_config.public_ip_address is not None:
                public_ip_address = self.network_client.public_ip_addresses.get(
                    self.config['resource_group'],
                    ip_config.public_ip_address.id.split('/')[-1]
                )
                self.public_ip = public_ip_address.ip_address

        return self.instance_data

    def get_instance_id(self):
        """
        Returns the instance ID
        """
        if not self.instance_id and self.instance_data:
            self.instance_id = self.instance_data.vm_id

        if not self.instance_id:
            instance_data = self.get_instance_data()
            if instance_data:
                self.instance_id = instance_data.vm_id
            else:
                logger.debug(f'VM instance {self.name} does not exists')

        return self.instance_id

    def get_private_ip(self):
        """
        Requests the private IP address
        """
        while not self.private_ip:
            self.get_instance_data()
            time.sleep(1)

        return self.private_ip

    def get_public_ip(self):
        """
        Requests the public IP address
        """
        if not self.public:
            return None

        while not self.public_ip or self.public_ip == '0.0.0.0':
            self.get_instance_data()
            time.sleep(1)

        return self.public_ip

    def create(self, check_if_exists=False, user_data=None):
        """
        Creates a new VM instance
        """
        vsi_exists = True if self.instance_id else False

        if check_if_exists and not vsi_exists:
            logger.debug(f'Checking if VM instance {self.name} already exists')
            instance_data = self.get_instance_data()
            if instance_data:
                logger.debug(f'VM instance {self.name} already exists')
                vsi_exists = True

        self._create_instance(user_data=user_data) if not vsi_exists else self.start()

        return self.instance_id

    def start(self):
        """
        Starts the VM instance
        """
        logger.info(f"Starting VM instance {self.name}")

        poller = self.compute_client.virtual_machines.begin_start(
            self.config['resource_group'], self.name
        )
        poller.result()
        self.public_ip = self.get_public_ip()

        logger.debug(f"VM instance {self.name} started successfully")

    def _delete_instance(self):
        """
        Deletes the VM instance and the associated volume
        """
        logger.debug(f"Deleting VM instance {self.name}")

        self.get_instance_data()

        logger.debug(f"Going to delete VM instance {self.name}")

        poller = self.compute_client.virtual_machines.begin_delete(
            self.config['resource_group'], self.name, force_deletion=True
        )
        poller.result()

        nic_name = self.instance_data.network_profile.network_interfaces[0].id.split('/')[-1]
        poller = self.network_client.network_interfaces.begin_delete(
            self.config['resource_group'], nic_name
        )
        # poller.result()

        disk_name = self.instance_data.storage_profile.os_disk.name
        poller = self.compute_client.disks.begin_delete(
            self.config['resource_group'], disk_name
        )
        # poller.result()

        self.instance_data = None
        self.instance_id = None
        self.private_ip = None
        self.public_ip = None
        self.del_ssh_client()

    def _stop_instance(self):
        """
        Stops the VM instance
        """
        logger.debug(f"Stopping VM instance {self.name}")
        try:
            self.compute_client.virtual_machines.begin_power_off(
                self.config['resource_group'], self.name
            )
        except Exception:
            if os.path.isfile(SA_DATA_FILE):
                os.system("shutdown -h now")

    def stop(self):
        """
        Stops the VM instance
        """
        if self.delete_on_dismantle:
            self._delete_instance()
        else:
            self._stop_instance()

    def delete(self):
        """
        Deletes the VM instance
        """
        self._delete_instance()

    def validate_capabilities(self):
        """
        Validate hardware/os requirments specified in backend config
        """
        pass
