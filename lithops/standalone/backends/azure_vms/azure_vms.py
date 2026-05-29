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
from azure.mgmt.compute.models import (
    HardwareProfile,
    ImageReference,
    LinuxConfiguration,
    ManagedDiskParameters,
    NetworkInterfaceReference,
    NetworkProfile,
    OSDisk,
    OSProfile,
    SshConfiguration,
    SshPublicKey,
    StorageProfile,
    VirtualMachine,
)
from azure.mgmt.network import NetworkManagementClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from lithops.version import __version__
from lithops.util.ssh_client import SSHClient, ssh_boot_status_message
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR, SA_CONFIG_FILE
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import (
    StandaloneMode,
    prepare_standalone_clean,
    standalone_clean_stop_early,
)
from lithops.standalone import LithopsValidationError


logger = logging.getLogger(__name__)

INSTANCE_START_TIMEOUT = 180
DEFAULT_UBUNTU_IMAGE = 'Canonical:ubuntu-24_04-lts:server:latest'


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

        self.vnet_data_type = 'provided' if 'vnet_name' in self.config else 'created'
        self.ssh_data_type = 'provided' if 'ssh_key_filename' in config else 'created'

        suffix = 'vm' if self.mode == StandaloneMode.CONSUME.value else 'vpc'
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, f'{self.location}_{suffix}_data')

        self.azure_data = None
        self.vnet_name = None
        self.vnet_key = None

        credential = DefaultAzureCredential()
        subscription_id = self.config['subscription_id']
        self.compute_client = ComputeManagementClient(credential, subscription_id)
        self.network_client = NetworkManagementClient(credential, subscription_id)

        self.master = None
        self.workers = []
        self.instance_types = {}
        self._init_created = None

        msg = COMPUTE_CLI_MSG.format('Azure Virtual Machines')
        logger.info(f"{msg} - Region: {self.location}")

    def is_initialized(self):
        """
        Checks if the backend is initialized
        """
        if self.mode == StandaloneMode.CONSUME.value:
            return True
        return os.path.isfile(self.cache_file)

    def _load_azure_vms_data(self):
        """
        Loads Azure data from local cache
        """
        self.azure_data = load_yaml_config(self.cache_file)

        if self.azure_data:
            logger.debug(f'Azure VMs data loaded from {self.cache_file}')

        if self.azure_data and 'vnet_name' in self.azure_data:
            self.vnet_key = self.azure_data['vnet_id'][-6:]
            self.vnet_name = self.azure_data['vnet_name']

    def _dump_azure_vms_data(self):
        """
        Dumps Azure data to local cache
        """
        dump_yaml_config(self.cache_file, self.azure_data)

    def _delete_vpc_data(self):
        """
        Deletes the vpc data file
        """
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)

    def _reset_init_created(self):
        self._init_created = {
            'vnet': False,
            'subnet': False,
            'nsg': False,
            'floating_ip': False,
            'ssh_key': False,
        }

    def _safe_rollback_delete(self, delete_fn, resource_desc):
        try:
            delete_fn()
        except ResourceNotFoundError:
            pass
        except Exception as err:
            logger.warning(f'Rollback: could not delete {resource_desc}: {err}')

    def _rollback_init_resources(self):
        """
        Deletes Azure resources created during a failed init().
        """
        if not self._init_created:
            return

        logger.info('Rolling back Azure VMs resources provisioned during failed init')
        rg = self.config['resource_group']
        created = self._init_created

        if created.get('floating_ip') and self.config.get('floating_ip_name'):
            fip_name = self.config['floating_ip_name']
            self._safe_rollback_delete(
                lambda: self.network_client.public_ip_addresses.begin_delete(rg, fip_name).result(),
                f'public IP {fip_name}',
            )

        if created.get('nsg') and self.config.get('security_group_name'):
            sg_name = self.config['security_group_name']
            self._safe_rollback_delete(
                lambda: self.network_client.network_security_groups.begin_delete(rg, sg_name).result(),
                f'network security group {sg_name}',
            )

        if created.get('subnet') and self.config.get('vnet_name') and self.config.get('subnet_name'):
            vnet_name = self.config['vnet_name']
            subnet_name = self.config['subnet_name']
            self._safe_rollback_delete(
                lambda: self.network_client.subnets.begin_delete(
                    rg, vnet_name, subnet_name
                ).result(),
                f'subnet {subnet_name}',
            )

        if created.get('vnet') and self.config.get('vnet_name'):
            vnet_name = self.config['vnet_name']
            self._safe_rollback_delete(
                lambda: self.network_client.virtual_networks.begin_delete(rg, vnet_name).result(),
                f'virtual network {vnet_name}',
            )

        if created.get('ssh_key'):
            key_filename = self.config.get('ssh_key_filename')
            if key_filename and 'lithops-key-' in key_filename:
                for path in (key_filename, f'{key_filename}.pub'):
                    if os.path.isfile(path):
                        os.remove(path)

        if self.vnet_data_type == 'created':
            self._delete_vpc_data()

        self._init_created = None

    def _create_vnet(self):
        """
        Creates a new Virtual Network
        """
        if 'vnet_name' in self.config:
            logger.debug(f'Using user-provided virtual network {self.config["vnet_name"]}')
            return

        if self.azure_data and 'vnet_name' in self.azure_data:
            vnets_info = list(self.network_client.virtual_networks.list(self.config['resource_group']))
            for vnet in vnets_info:
                if vnet.name == self.vnet_name:
                    self.config['vnet_id'] = vnet.id
                    self.config['vnet_name'] = vnet.name
                    logger.debug(f'Using existing virtual network {vnet.name}')
                    return

        self.vnet_name = self.config.get('vnet_name', f'lithops-vnet-{str(uuid.uuid4())[-6:]}')
        logger.debug(f'Setting virtual network name to: {self.vnet_name}')

        assert re.match("^[a-z0-9-:-]*$", self.vnet_name), \
            f'Virtual network name "{self.vnet_name}" not valid'

        vnets_info = list(self.network_client.virtual_networks.list(self.config['resource_group']))
        for vnet in vnets_info:
            if vnet.name == self.vnet_name:
                self.config['vnet_id'] = vnet.id
                self.config['vnet_name'] = vnet.name
                logger.debug(f'Using existing virtual network {vnet.name}')
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
            self.config['vnet_id'] = vnet_result.id
            self.config['vnet_name'] = vnet_result.name
            if self._init_created is not None:
                self._init_created['vnet'] = True

    def _create_subnet(self):
        """
        Creates a new subnet
        """
        if 'subnet_name' in self.config:
            logger.debug(f'Using user-provided virtual subnet {self.config["subnet_name"]}')
            return

        if self.azure_data and 'subnet_name' in self.azure_data:
            subnets_info = list(self.network_client.subnets.list(self.config['resource_group'], self.vnet_name))
            for subnet in subnets_info:
                if subnet.name == self.azure_data['subnet_name']:
                    self.config['subnet_id'] = subnet.id
                    self.config['subnet_name'] = subnet.name
                    logger.debug(f'Using existing virtual subnet {subnet.name}')
                    return

        self.subnet_name = self.vnet_name + '-subnet'

        subnets_info = list(self.network_client.subnets.list(self.config['resource_group'], self.vnet_name))
        for subnet in subnets_info:
            if subnet.name == self.subnet_name:
                self.config['subnet_id'] = subnet.id
                self.config['subnet_name'] = subnet.name
                logger.debug(f'Using existing virtual subnet {subnet.name}')
                break

        if 'subnet_name' not in self.config:
            logger.debug(f'Creating virtual subnet {self.subnet_name}')
            poller = self.network_client.subnets.begin_create_or_update(
                self.config['resource_group'],
                self.vnet_name,
                self.subnet_name,
                {"address_prefix": "10.0.0.0/24"},
            )
            subnet_result = poller.result()
            self.config['subnet_id'] = subnet_result.id
            self.config['subnet_name'] = subnet_result.name
            if self._init_created is not None:
                self._init_created['subnet'] = True

    def _use_security_group(self, sg_info):
        """
        Reuse an existing security group when it is in the configured region.
        """
        if sg_info.location.lower() != self.location.lower():
            logger.debug(
                f'Skipping security group {sg_info.name} in {sg_info.location}; '
                f'expected region {self.location}'
            )
            return False

        self.config['security_group_id'] = sg_info.id
        self.config['security_group_name'] = sg_info.name
        logger.debug(
            f'Using existing network security group {sg_info.name} in {sg_info.location}'
        )
        return True

    def _create_security_group(self):
        """
        Creates a new Security group
        """
        if 'security_group_id' in self.config:
            logger.debug(
                f'Using user-provided network security group '
                f'{self.config.get("security_group_name", self.config["security_group_id"])}'
            )
            return

        if self.azure_data and 'security_group_id' in self.azure_data:
            try:
                sg_info = self.network_client.network_security_groups.get(
                    self.config['resource_group'], self.azure_data['security_group_name']
                )
                if self._use_security_group(sg_info):
                    return
            except ResourceNotFoundError:
                pass

        security_group_name = 'lithops-security-group'

        try:
            sg_info = self.network_client.network_security_groups.get(
                self.config['resource_group'], security_group_name
            )
            self._use_security_group(sg_info)
        except ResourceNotFoundError:
            pass

        if 'security_group_id' not in self.config:
            logger.debug(f'Creating network security group {security_group_name}')
            nsg_rules = [
                {
                    "name": "allow-ssh",
                    "protocol": "Tcp",
                    "sourcePortRange": "*",
                    "destinationPortRange": "22",
                    "sourceAddressPrefix": "*",
                    "destinationAddressPrefix": "*",
                    "access": "Allow",
                    "direction": "Inbound",
                    "priority": 100
                },
                {
                    "name": "allow-master-port-8080",
                    "protocol": "Tcp",
                    "sourcePortRange": "*",
                    "destinationPortRange": "8080",
                    "sourceAddressPrefix": "10.0.0.0/24",
                    "destinationAddressPrefix": "*",
                    "access": "Allow",
                    "direction": "Inbound",
                    "priority": 101
                },
                {
                    "name": "allow-worker-port-8081",
                    "protocol": "Tcp",
                    "sourcePortRange": "*",
                    "destinationPortRange": "8081",
                    "sourceAddressPrefix": "10.0.0.0/24",
                    "destinationAddressPrefix": "*",
                    "access": "Allow",
                    "direction": "Inbound",
                    "priority": 102
                },
                {
                    "name": "allow-redis-port-6379",
                    "protocol": "Tcp",
                    "sourcePortRange": "*",
                    "destinationPortRange": "6379",
                    "sourceAddressPrefix": "10.0.0.0/24",
                    "destinationAddressPrefix": "*",
                    "access": "Allow",
                    "direction": "Inbound",
                    "priority": 103
                }
            ]

            # Define the network security group to contain the rule
            network_security_group = {
                "location": self.location,
                "securityRules": nsg_rules
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
            if self._init_created is not None:
                self._init_created['nsg'] = True

    def _create_master_floating_ip(self):
        """
        Creates the master VM floating IP address
        """

        def get_floating_ip(fip_name):
            try:
                fip_info = self.network_client.public_ip_addresses.get(
                    self.config['resource_group'], fip_name
                )
                self.config['floating_ip'] = fip_info.ip_address
                self.config['floating_ip_name'] = fip_info.name
                self.config['floating_ip_id'] = fip_info.id
                logger.debug(
                    f'Using existing public IP address {fip_info.ip_address} ({fip_info.name})'
                )
            except ResourceNotFoundError:
                pass

        if self.azure_data and 'floating_ip_id' in self.azure_data:
            get_floating_ip(self.azure_data['floating_ip_name'])

        floating_ip_name = self.vnet_name + '-ip'

        if 'floating_ip_id' not in self.config:
            get_floating_ip(floating_ip_name)

        if 'floating_ip_id' not in self.config:
            logger.debug(f'Creating public IP address {floating_ip_name}')
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
            self.config['floating_ip'] = ip_address_result.ip_address
            self.config['floating_ip_name'] = ip_address_result.name
            self.config['floating_ip_id'] = ip_address_result.id
            if self._init_created is not None:
                self._init_created['floating_ip'] = True

    def _create_ssh_key(self):
        """
        Creates a new ssh key pair
        """
        if 'ssh_key_filename' in self.config:
            logger.debug(f'Using user-provided SSH key pair {self.config["ssh_key_filename"]}')
            return

        if self.azure_data and 'ssh_key_filename' in self.azure_data:
            if os.path.isfile(self.azure_data['ssh_key_filename']):
                self.config['ssh_key_filename'] = self.azure_data['ssh_key_filename']
                logger.debug(f'Using existing SSH key pair {self.config["ssh_key_filename"]}')
                return

        keyname = f'lithops-key-{str(uuid.uuid4())[-8:]}'
        filename = os.path.join("~", ".ssh", f"{keyname}.{self.name}.id_rsa")
        key_filename = os.path.expanduser(filename)

        if not os.path.isfile(key_filename):
            logger.debug("Generating new ssh key pair")
            os.system(f'ssh-keygen -b 2048 -t rsa -f {key_filename} -q -N ""')
            logger.debug(f"SHH key pair generated: {key_filename}")
            if self._init_created is not None:
                self._init_created['ssh_key'] = True

        self.config['ssh_key_filename'] = key_filename

    def _get_all_instance_types(self):
        """
        Get all virtual machine sizes in the specified location
        """
        if self.azure_data and 'instance_types' in self.azure_data:
            self.instance_types = self.azure_data['instance_types']
            return

        vm_sizes = self.compute_client.virtual_machine_sizes.list(self.location)

        instances = {}

        for vm_size in vm_sizes:
            instance_name = vm_size.name
            cpu_count = vm_size.number_of_cores
            instances[instance_name] = cpu_count

        self.instance_types = instances

    def _create_master_instance(self):
        """
        Creates the master VM insatnce
        """
        name = self.config.get('master_name') or f'lithops-master-{self.vnet_key}'
        self.master = VMInstance(name, self.config, self.compute_client, public=True)
        self.master.name = self.config['instance_name'] if self.mode == StandaloneMode.CONSUME.value else name
        self.master.public_ip = self.config['floating_ip'] if self.mode != StandaloneMode.CONSUME.value else '0.0.0.0'
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

        if self.mode == StandaloneMode.CONSUME.value:
            if 'master_instance_type' not in self.config:
                try:
                    instance_data = self.compute_client.virtual_machines.get(
                        self.config['resource_group'], self.config['instance_name']
                    )
                except ResourceNotFoundError:
                    raise Exception(
                        f"VM Instance {self.config['instance_name']} does not exist"
                    )
                self.config['master_instance_type'] = instance_data.hardware_profile.vm_size
            self._create_master_instance()
            return

        self._load_azure_vms_data()

        if self.mode in [StandaloneMode.CREATE.value, StandaloneMode.REUSE.value]:

            self._reset_init_created()
            try:
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
                # Request instance types
                self._get_all_instance_types()

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
                    'floating_ip_name': self.config['floating_ip_name'],
                    'instance_types': self.instance_types
                }
                self._dump_azure_vms_data()
            except Exception:
                self._rollback_init_resources()
                raise
            finally:
                self._init_created = None

    def build_image(self, image_name, script_file, overwrite, include, extra_args=[]):
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
        Deletes Lithops VM instances in the resource group.
        When all=True, every lithops master/worker is removed (any VNet).
        """
        if all:
            logger.info(f'Deleting all Lithops VMs in {self.config["resource_group"]}')
        else:
            logger.info(f'Deleting Lithops worker VMs from {self.azure_data["vnet_name"]}')

        vms_prefixes = ('lithops-worker', 'lithops-master') if all else ('lithops-worker',)

        instances_to_delete = []
        vms_info = self.compute_client.virtual_machines.list(self.config['resource_group'])
        for vm in vms_info:
            if 'type' not in vm.tags or vm.tags['type'] != 'lithops-runtime':
                continue
            if not vm.name.startswith(vms_prefixes):
                continue
            if not all and vm.tags.get('lithops_vnet') != self.vnet_name:
                continue
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

        if all and self.azure_data:
            master_pk = os.path.join(
                self.cache_dir, f"{self.azure_data['master_name']}-id_rsa.pub"
            )
            if os.path.isfile(master_pk):
                os.remove(master_pk)

        if self.azure_data and self.azure_data.get('vnet_data_type') == 'provided':
            return

    def _try_delete_security_group(self, security_group_name):
        """
        Delete the Lithops NSG if it is no longer attached to any NIC.
        """
        if not security_group_name:
            return

        try:
            logger.debug(f'Deleting network security group {security_group_name}')
            self.network_client.network_security_groups.begin_delete(
                self.config['resource_group'],
                security_group_name,
            ).result()
        except ResourceNotFoundError:
            pass
        except HttpResponseError as err:
            if 'InUseNetworkSecurityGroupCannotBeDeleted' in str(err):
                logger.warning(
                    f'Network security group {security_group_name} is still in use; '
                    'delete remaining Lithops VMs/NICs and run clean again'
                )
            else:
                logger.warning(f'Could not delete network security group {security_group_name}: {err}')

    def _delete_vnet_and_subnet(self, delete_security_group=False):
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

        if delete_security_group:
            self._try_delete_security_group(self.azure_data.get('security_group_name'))

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
        Clean Lithops resources for the configured region (cache file for
        ``location`` in config). Same flow as the other standalone cloud backends.
        """
        logger.info('Cleaning Azure Virtual Machines resources')

        prepare_standalone_clean(self, self._load_azure_vms_data)
        if standalone_clean_stop_early(
                self, self.azure_data, self._delete_vpc_data, all):
            return True

        self._delete_vm_instances(all=all)
        if all:
            self._delete_vnet_and_subnet(delete_security_group=True)
            self._delete_ssh_key()
            self._delete_vpc_data()

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

        if include_master:
            self.master.stop()

    def get_instance(self, name, **kwargs):
        """
        Returns a VM class instance.
        Does not creates nor starts a VM instance
        """
        instance = VMInstance(name, self.config, self.compute_client)

        for key in kwargs:
            if hasattr(instance, key) and kwargs[key] is not None:
                setattr(instance, key, kwargs[key])

        return instance

    def get_worker_instance_type(self):
        """
        Return the worker profile name
        """
        return self.config['worker_instance_type']

    def get_worker_cpu_count(self):
        """
        Returns the number of CPUs in the worker instance type
        """
        return self.instance_types[self.config['worker_instance_type']]

    def create_worker(self, name):
        """
        Creates a new worker VM instance
        """
        worker = VMInstance(name, self.config, self.compute_client, public=False)
        ssh_key = f'{self.cache_dir}/{self.master.name}-id_rsa'
        worker.ssh_credentials['key_filename'] = ssh_key
        worker.ssh_credentials.pop('password')
        worker.create()
        worker.ssh_credentials['key_filename'] = '~/.ssh/lithops_id_rsa'
        self.workers.append(worker)

    def get_runtime_key(self, runtime_name, version=__version__):
        """
        Creates the runtime key
        """
        name = runtime_name.replace('/', '-').replace(':', '-')
        if self.mode == StandaloneMode.CONSUME.value:
            master_id = self.master.instance_id
        else:
            master_id = self.azure_data['master_id']
        runtime_key = os.path.join(self.name, version, master_id, name)
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
        try:
            self.get_ssh_client().run_remote_command('id')
        except LithopsValidationError as err:
            raise err
        except Exception as err:
            ip = self.public_ip if self.public else self.private_ip
            logger.debug(f'SSH to {ip}: {ssh_boot_status_message(err)}')
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

    def _rollback_instance_resources(self, vm_created=False, nic_created=False, public_ip_created=False):
        """
        Deletes VM instance resources provisioned during a failed create().
        """
        rg = self.config['resource_group']
        logger.info(f'Rolling back resources provisioned for {self.name}')

        if vm_created:
            try:
                self._delete_instance()
            except Exception as err:
                logger.warning(f'Rollback: could not delete VM {self.name}: {err}')

        if nic_created and not vm_created:
            nic_name = self.name + '-nic'
            try:
                self.network_client.network_interfaces.begin_delete(rg, nic_name).result()
            except ResourceNotFoundError:
                pass
            except Exception as err:
                logger.warning(f'Rollback: could not delete NIC {nic_name}: {err}')

        if public_ip_created:
            ip_name = self.name + '-ip'
            try:
                self.network_client.public_ip_addresses.begin_delete(rg, ip_name).result()
            except ResourceNotFoundError:
                pass
            except Exception as err:
                logger.warning(f'Rollback: could not delete public IP {ip_name}: {err}')

    def _create_instance(self, user_data=None):
        """
        Creates a new VM instance
        """
        logger.debug(f"Creating new VM instance {self.name}")

        nic_created = False
        public_ip_created = False
        vm_created = False

        # Create NIC
        nic_params = {
            'location': self.location,
            'ip_configurations': [{
                'name': 'ipconfig1',
                'subnet': {'id': self.config['subnet_id']},
            }],
            "network_security_group": {"id": self.config['security_group_id']}
        }

        try:
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
                public_ip_created = True
                self.public_ip = ip_address_result.ip_address
                nic_params['ip_configurations'][0]['public_ip_address'] = {"id": ip_address_result.id}

            elif self.public:
                nic_params['ip_configurations'][0]['public_ip_address'] = {"id": self.config['floating_ip_id']}

            poller = self.network_client.network_interfaces.begin_create_or_update(
                self.config['resource_group'],
                self.name + '-nic',
                nic_params
            )
            nic_data = poller.result()
            nic_created = True
            self.private_ip = nic_data.ip_configurations[0].private_ip_address

            # Create VM
            vm_username = self.ssh_credentials['username']
            with open(self.ssh_credentials['key_filename'] + '.pub', 'r') as pk:
                vm_pk_data = pk.read().strip()

            image_publisher, image_offer, image_sku, image_version = DEFAULT_UBUNTU_IMAGE.split(':')
            image_reference = (
                ImageReference(id=self.config['image_id'])
                if 'image_id' in self.config
                else ImageReference(
                    publisher=image_publisher,
                    offer=image_offer,
                    sku=image_sku,
                    version=image_version,
                )
            )

            vm = VirtualMachine(
                location=self.location,
                tags={
                    'type': 'lithops-runtime',
                    'lithops_version': str(__version__),
                    'lithops_vnet': self.config['vnet_name'],
                },
                os_profile=OSProfile(
                    computer_name=self.name,
                    admin_username=vm_username,
                    linux_configuration=LinuxConfiguration(
                        disable_password_authentication=True,
                        ssh=SshConfiguration(
                            public_keys=[
                                SshPublicKey(
                                    path=f'/home/{vm_username}/.ssh/authorized_keys',
                                    key_data=vm_pk_data,
                                )
                            ]
                        ),
                    ),
                ),
                hardware_profile=HardwareProfile(vm_size=self.instance_type),
                storage_profile=StorageProfile(
                    image_reference=image_reference,
                    os_disk=OSDisk(
                        name=self.name + '-osdisk',
                        create_option='FromImage',
                        managed_disk=ManagedDiskParameters(
                            storage_account_type='Standard_LRS',
                        ),
                    ),
                ),
                network_profile=NetworkProfile(
                    network_interfaces=[
                        NetworkInterfaceReference(id=nic_data.id, primary=True)
                    ]
                ),
            )

            poller = self.compute_client.virtual_machines.begin_create_or_update(
                self.config['resource_group'],
                self.name,
                vm
            )

            self.instance_data = poller.result()
            vm_created = True
            self.instance_id = self.instance_data.vm_id

            return self.instance_data
        except Exception:
            self._rollback_instance_resources(
                vm_created=vm_created,
                nic_created=nic_created,
                public_ip_created=public_ip_created,
            )
            raise

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
            if os.path.isfile(SA_CONFIG_FILE):
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
