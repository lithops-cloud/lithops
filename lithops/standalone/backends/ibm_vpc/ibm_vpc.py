#
# Copyright Cloudlab URV 2020
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

import re
import os
import time
import logging
from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException
from concurrent.futures import ThreadPoolExecutor

from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR
from lithops.config import load_yaml_config, dump_yaml_config
from . import config as vpc_config


logger = logging.getLogger(__name__)


class IBMVPCBackend:

    def __init__(self, ibm_vpc_config, mode):
        logger.debug("Creating IBM VPC client")
        self.name = 'ibm_vpc'
        self.config = ibm_vpc_config
        self.mode = mode

        self.endpoint = self.config['endpoint']
        self.region = self.endpoint.split('//')[1].split('.')[0]
        self.vpc_name = self.config.get('vpc_name')

        logger.debug('Setting VPC endpoint to: {}'.format(self.endpoint))

        self.master = None
        self.workers = []

        iam_api_key = self.config.get('iam_api_key')
        self.custom_image = self.config.get('custom_lithops_image')

        authenticator = IAMAuthenticator(iam_api_key)
        self.ibm_vpc_client = VpcV1('2021-08-31', authenticator=authenticator)
        self.ibm_vpc_client.set_service_url(self.config['endpoint'] + '/v1')

        user_agent_string = 'ibm_vpc_{}'.format(self.config['user_agent'])
        self.ibm_vpc_client._set_user_agent_header(user_agent_string)

        msg = COMPUTE_CLI_MSG.format('IBM VPC')
        logger.info("{} - Region: {}".format(msg, self.region))

    def _create_vpc(self, vpc_data):
        """
        Creates a new VPC
        """
        if 'vpc_id' in self.config:
            return

        if 'vpc_id' in vpc_data:
            self.config['vpc_id'] = vpc_data['vpc_id']
            self.config['security_group_id'] = vpc_data['security_group_id']
            return

        vpc_info = None

        assert re.match("^[a-z0-9-:-]*$", self.vpc_name),\
            'VPC name "{}" not valid'.format(self.vpc_name)

        vpcs_info = self.ibm_vpc_client.list_vpcs().get_result()
        for vpc in vpcs_info['vpcs']:
            if vpc['name'] == self.vpc_name:
                vpc_info = vpc

        if not vpc_info:
            logger.debug('Creating VPC {}'.format(self.vpc_name))
            vpc_prototype = {}
            vpc_prototype['address_prefix_management'] = 'auto'
            vpc_prototype['classic_access'] = False
            vpc_prototype['name'] = self.vpc_name
            vpc_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.ibm_vpc_client.create_vpc(**vpc_prototype)
            vpc_info = response.result

        self.config['vpc_id'] = vpc_info['id']
        self.config['security_group_id'] = vpc_info['default_security_group']['id']

        deloy_ssh_rule = True
        deploy_icmp_rule = True

        sg_rule_prototype_ssh = {}
        sg_rule_prototype_ssh['direction'] = 'inbound'
        sg_rule_prototype_ssh['ip_version'] = 'ipv4'
        sg_rule_prototype_ssh['protocol'] = 'tcp'
        sg_rule_prototype_ssh['port_min'] = 22
        sg_rule_prototype_ssh['port_max'] = 22

        sg_rule_prototype_icmp = {}
        sg_rule_prototype_icmp['direction'] = 'inbound'
        sg_rule_prototype_icmp['ip_version'] = 'ipv4'
        sg_rule_prototype_icmp['protocol'] = 'icmp'
        sg_rule_prototype_icmp['type'] = 8

        sg_rules = self.ibm_vpc_client.get_security_group(self.config['security_group_id'])
        for rule in sg_rules.get_result()['rules']:
            if all(item in rule.items() for item in sg_rule_prototype_ssh.items()):
                deloy_ssh_rule = False
            if all(item in rule.items() for item in sg_rule_prototype_icmp.items()):
                deploy_icmp_rule = False

        if deloy_ssh_rule:
            self.ibm_vpc_client.create_security_group_rule(self.config['security_group_id'],
                                                           sg_rule_prototype_ssh)
        if deploy_icmp_rule:
            self.ibm_vpc_client.create_security_group_rule(self.config['security_group_id'],
                                                           sg_rule_prototype_icmp)

    def _create_gateway(self, vpc_data):
        """
        Crates a public gateway.
        Gateway is used by private nodes for accessing internet
        """
        if 'gateway_id' in self.config:
            return

        if 'gateway_id' in vpc_data:
            self.config['gateway_id'] = vpc_data['gateway_id']
            return

        gateway_name = 'lithops-gateway-{}'.format(self.vpc_key)
        gateway_data = None

        gateways_info = self.ibm_vpc_client.list_public_gateways().get_result()
        for gw in gateways_info['public_gateways']:
            if gw['vpc']['id'] == self.config['vpc_id']:
                gateway_data = gw

        if not gateway_data:
            logger.debug('Creating Gateway {}'.format(gateway_name))
            gateway_prototype = {}
            gateway_prototype['vpc'] = {'id': self.config['vpc_id']}
            gateway_prototype['zone'] = {'name': self.config['zone_name']}
            gateway_prototype['name'] = gateway_name
            response = self.ibm_vpc_client.create_public_gateway(**gateway_prototype)
            gateway_data = response.result

        self.config['gateway_id'] = gateway_data['id']

    def _create_subnet(self, vpc_data):
        """
        Creates a new subnet
        """
        if 'subnet_id' in self.config:
            return

        if 'subnet_id' in vpc_data:
            self.config['subnet_id'] = vpc_data['subnet_id']
            return

        subnet_name = 'lithops-subnet-{}'.format(self.vpc_key)
        subnet_data = None

        subnets_info = self.ibm_vpc_client.list_subnets(resource_group_id=self.config['resource_group_id']).get_result()
        for sn in subnets_info['subnets']:
            if sn['name'] == subnet_name:
                subnet_data = sn

        if not subnet_data:
            logger.debug('Creating Subnet {}'.format(subnet_name))
            subnet_prototype = {}
            subnet_prototype['zone'] = {'name': self.config['zone_name']}
            subnet_prototype['ip_version'] = 'ipv4'
            subnet_prototype['name'] = subnet_name
            subnet_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            subnet_prototype['vpc'] = {'id': self.config['vpc_id']}
            subnet_prototype['ipv4_cidr_block'] = '10.241.64.0/22'
            response = self.ibm_vpc_client.create_subnet(subnet_prototype)
            subnet_data = response.result

        self.config['subnet_id'] = subnet_data['id']

        # Attach public gateway to the subnet
        self.ibm_vpc_client.set_subnet_public_gateway(self.config['subnet_id'],
                                                      {'id': self.config['gateway_id']})

    def _create_floating_ip(self, vpc_data):
        """
        Creates a new floating IP address
        """
        if 'floating_ip_id' in self.config:
            return

        if 'floating_ip_id' in vpc_data:
            self.config['floating_ip'] = vpc_data['floating_ip']
            self.config['floating_ip_id'] = vpc_data['floating_ip_id']
            return

        floating_ip_name = 'lithops-floatingip-{}'.format(self.vpc_key)
        floating_ip_data = None

        floating_ips_info = self.ibm_vpc_client.list_floating_ips().get_result()
        for fip in floating_ips_info['floating_ips']:
            if fip['name'] == floating_ip_name:
                floating_ip_data = fip

        if not floating_ip_data:
            logger.debug('Creating floating IP {}'.format(floating_ip_name))
            floating_ip_prototype = {}
            floating_ip_prototype['name'] = floating_ip_name
            floating_ip_prototype['zone'] = {'name': self.config['zone_name']}
            floating_ip_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.ibm_vpc_client.create_floating_ip(floating_ip_prototype)
            floating_ip_data = response.result

        self.config['floating_ip'] = floating_ip_data['address']
        self.config['floating_ip_id'] = floating_ip_data['id']

    def init(self):
        """
        Initialize the VPC
        """
        vpc_data_filename = os.path.join(CACHE_DIR, self.name, 'data')
        self.vpc_data = load_yaml_config(vpc_data_filename)

        cahced_mode = self.vpc_data.get('mode')
        cahced_instance_id = self.vpc_data.get('instance_id')

        if self.mode == 'consume':
            logger.debug('Initializing IBM VPC backend (Consume mode)')

            if self.mode != cahced_mode or self.config['instance_id'] != cahced_instance_id:
                ins_id = self.config['instance_id']
                instance_data = self.ibm_vpc_client.get_instance(ins_id)
                name = instance_data.get_result()['name']
                self.vpc_data = {'mode': 'consume',
                                 'instance_id': self.config['instance_id'],
                                 'instance_name': name,
                                 'floating_ip': self.config['ip_address']}
                dump_yaml_config(vpc_data_filename, self.vpc_data)

            self.master = IBMVPCInstance(self.vpc_data['instance_name'], self.config,
                                         self.ibm_vpc_client, public=True)
            self.master.instance_id = self.config['instance_id']
            self.master.public_ip = self.config['ip_address']
            self.master.delete_on_dismantle = False

        elif self.mode in ['create', 'reuse']:
            logger.debug(f'Initializing IBM VPC backend ({self.mode} mode)')

            if self.mode != cahced_mode:
                # invalidate cached data
                self.vpc_data = {}

            # Create the VPC if not exists
            self._create_vpc(self.vpc_data)
            # Set the prefix used for the VPC resources
            self.vpc_key = self.config['vpc_id'].split('-')[2]
            # Create a new gateway if not exists
            self._create_gateway(self.vpc_data)
            # Create a new subnaet if not exists
            self._create_subnet(self.vpc_data)
            # Create a new floating IP if not exists
            self._create_floating_ip(self.vpc_data)

            # create the master VM insatnce
            name = 'lithops-master-{}'.format(self.vpc_key)
            self.master = IBMVPCInstance(name, self.config, self.ibm_vpc_client, public=True)
            self.master.public_ip = self.config['floating_ip']
            self.master.profile_name = self.config['master_profile_name']
            self.master.delete_on_dismantle = False

            self.vpc_data = {
                'mode': 'consume',
                'instance_id': '0af1',
                'instance_name': self.master.name,
                'vpc_id': self.config['vpc_id'],
                'subnet_id': self.config['subnet_id'],
                'security_group_id': self.config['security_group_id'],
                'floating_ip': self.config['floating_ip'],
                'floating_ip_id': self.config['floating_ip_id'],
                'gateway_id': self.config['gateway_id']
            }

            dump_yaml_config(vpc_data_filename, self.vpc_data)

    def _delete_vm_instances(self):
        """
        Deletes all VM instances in the VPC
        """
        msg = ('Deleting all Lithops worker VMs in {}'.format(self.vpc_name)
               if self.vpc_name else 'Deleting all Lithops worker VMs')
        logger.info(msg)

        def delete_instance(instance_info):
            ins_name, ins_id = instance_info
            try:
                logger.info('Deleting instance {}'.format(ins_name))
                self.ibm_vpc_client.delete_instance(ins_id)
            except ApiException as e:
                if e.code == 404:
                    pass
                else:
                    raise e

        deleted_instances = set()
        while True:
            instances_to_delete = set()
            instances_info = self.ibm_vpc_client.list_instances().get_result()
            for ins in instances_info['instances']:
                if ins['name'].startswith('lithops-worker'):
                    ins_to_dlete = (ins['name'], ins['id'])
                    if ins_to_dlete not in deleted_instances:
                        instances_to_delete.add(ins_to_dlete)

            if instances_to_delete:
                with ThreadPoolExecutor(len(instances_to_delete)) as executor:
                    executor.map(delete_instance, instances_to_delete)
                deleted_instances.update(instances_to_delete)
            else:
                break
        # time.sleep(5)

    def _delete_subnet(self, vpc_data):
        """
        Deletes all VM instances in the VPC
        """
        subnet_name = 'lithops-subnet-{}'.format(self.vpc_key)
        if 'subnet_id' not in vpc_data:
            subnets_info = self.ibm_vpc_client.list_subnets().get_result()

            for subn in subnets_info['subnets']:
                if subn['name'] == subnet_name:
                    vpc_data['subnet_id'] = subn['id']

        if 'subnet_id' in vpc_data:
            logger.info('Deleting subnet {}'.format(subnet_name))
            try:
                self.ibm_vpc_client.delete_subnet(vpc_data['subnet_id'])
            except ApiException as e:
                if e.code == 404:
                    pass
                else:
                    raise e
            time.sleep(5)

    def _delete_gateway(self, vpc_data):
        """
        Deletes the public gateway
        """
        gateway_name = 'lithops-gateway-{}'.format(self.vpc_key)
        if 'gateway_id' not in vpc_data:
            gateways_info = self.ibm_vpc_client.list_public_gateways().get_result()

            for gw in gateways_info['public_gateways']:
                if ['name'] == gateway_name:
                    vpc_data['gateway_id'] = gw['id']

        if 'gateway_id' in vpc_data:
            logger.info('Deleting gateway {}'.format(gateway_name))
            try:
                self.ibm_vpc_client.delete_public_gateway(vpc_data['gateway_id'])
            except ApiException as e:
                if e.code == 404:
                    pass
                elif e.code == 400:
                    pass
                else:
                    raise e
            time.sleep(5)

    def _delete_vpc(self, vpc_data):
        """
        Deletes the VPC
        """
        if 'vpc_id' not in vpc_data:
            vpcs_info = self.ibm_vpc_client.list_vpcs().get_result()
            for vpc in vpcs_info['vpcs']:
                if vpc['name'] == self.vpc_name:
                    vpc_data['vpc_id'] = vpc['id']

        if 'vpc_id' in vpc_data:
            logger.info('Deleting VPC {}'.format(self.vpc_name))
            try:
                self.ibm_vpc_client.delete_vpc(vpc_data['vpc_id'])
            except ApiException as e:
                if e.code == 404:
                    pass
                else:
                    raise e

    def clean(self):
        """
        Clean all the backend resources
        The gateway public IP and the floating IP are never deleted
        """
        logger.debug('Cleaning IBM VPC resources')
        # vpc_data_filename = os.path.join(CACHE_DIR, self.name, 'data')
        # vpc_data = load_yaml_config(vpc_data_filename)

        self._delete_vm_instances()
        # self._delete_gateway(vpc_data)
        # self._delete_subnet(vpc_data)
        # self._delete_vpc(vpc_data)

    def clear(self, job_keys=None):
        """
        Delete all the workers
        """
        # clear() is automatically called after get_result(),
        # so no need to stop the master VM.
        self.dismantle(include_master=False)

    def dismantle(self, include_master=True):
        """
        Stop all worker VM instances
        """
        if len(self.workers) > 0:
            with ThreadPoolExecutor(len(self.workers)) as ex:
                ex.map(lambda worker: worker.stop(), self.workers)
            self.workers = []

        if include_master and self.mode == 'consume':
            # in consume mode master VM is a worker
            self.master.stop()

    def get_vm(self, name):
        """
        Returns a VM class instance.
        Does not creates nor starts a VM instance
        """
        return IBMVPCInstance(name, self.config, self.ibm_vpc_client)

    def create_worker(self, name):
        """
        Creates a new worker VM instance in VPC
        """
        vm = IBMVPCInstance(name, self.config, self.ibm_vpc_client)
        vm.create(start=True)
        vm.ssh_credentials.pop('key_filename', None)
        self.workers.append(vm)

    def get_runtime_key(self, runtime_name):
        name = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = '/'.join([self.name, self.vpc_data['instance_id'], name])
        return runtime_key


class IBMVPCInstance:

    def __init__(self, name, ibm_vpc_config, ibm_vpc_client=None, public=False):
        """
        Initialize a IBMVPCInstance instance
        VMs can have master role, this means they will have a public IP address
        """
        self.name = name.lower()
        self.config = ibm_vpc_config

        self.delete_on_dismantle = self.config['delete_on_dismantle']
        self.profile_name = self.config['profile_name']

        self.ibm_vpc_client = ibm_vpc_client or self._create_vpc_client()
        self.public = public

        self.ssh_client = None
        self.instance_id = None
        self.instance_data = None
        self.ip_address = None
        self.public_ip = None

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', None)
        }

    def __str__(self):
        return 'VM instance {} ({})'.format(self.name, self.public_ip or self.ip_address)

    def _create_vpc_client(self):
        """
        Creates an IBM VPC python-sdk instance
        """
        authenticator = IAMAuthenticator(self.iam_api_key)
        ibm_vpc_client = VpcV1('2021-08-31', authenticator=authenticator)
        ibm_vpc_client.set_service_url(self.config['endpoint'] + '/v1')

        return ibm_vpc_client

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM only if the Instance is the master
        """
        if self.ip_address or self.public_ip:
            if not self.ssh_client:
                self.ssh_client = SSHClient(self.public_ip or self.ip_address, self.ssh_credentials)
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

    def _create_instance(self):
        """
        Creates a new VM instance
        """
        logger.debug("Creating new VM instance {}".format(self.name))

        security_group_identity_model = {'id': self.config['security_group_id']}
        subnet_identity_model = {'id': self.config['subnet_id']}
        primary_network_interface = {
            'name': 'eth0',
            'subnet': subnet_identity_model,
            'security_groups': [security_group_identity_model]
        }

        boot_volume_data = {
            'capacity': self.config['boot_volume_capacity'],
            'name': '{}-boot'.format(self.name),
            'profile': {'name': self.config['boot_volume_profile']}}

        boot_volume_attachment = {
            'delete_volume_on_instance_delete': True,
            'volume': boot_volume_data
        }

        key_identity_model = {'id': self.config['key_id']}

        instance_prototype = {}
        instance_prototype['name'] = self.name
        instance_prototype['keys'] = [key_identity_model]
        instance_prototype['profile'] = {'name': self.profile_name}
        instance_prototype['resource_group'] = {'id': self.config['resource_group_id']}
        instance_prototype['vpc'] = {'id': self.config['vpc_id']}
        instance_prototype['image'] = {'id': self.config['image_id']}
        instance_prototype['zone'] = {'name': self.config['zone_name']}
        instance_prototype['boot_volume_attachment'] = boot_volume_attachment
        instance_prototype['primary_network_interface'] = primary_network_interface

        if not self.public:
            user = self.config['ssh_username']
            token = self.config['ssh_password']
            instance_prototype['user_data'] = vpc_config.CLOUD_CONFIG.format(user, token)

        try:
            resp = self.ibm_vpc_client.create_instance(instance_prototype)
        except ApiException as e:
            if e.code == 400 and 'already exists' in e.message:
                return self.get_instance_data()
            elif e.code == 400 and 'over quota' in e.message:
                logger.debug("Create VM instance {} failed due to quota limit"
                             .format(self.name))
            else:
                logger.debug("Create VM instance {} failed with status code {}: {}"
                             .format(self.name, str(e.code), e.message))
            raise e

        logger.debug("VM instance {} created successfully ".format(self.name))

        return resp.result

    def _attach_floating_ip(self, instance):
        """
        Attach a floating IP address only if the VM is the master instance
        """

        fip = self.config['floating_ip']
        fip_id = self.config['floating_ip_id']

        # logger.debug('Attaching floating IP {} to VM instance {}'.format(fip, instance['id']))

        # we need to check if floating ip is not attached already. if not, attach it to instance
        instance_primary_ni = instance['primary_network_interface']

        if instance_primary_ni['primary_ipv4_address'] and instance_primary_ni['id'] == fip_id:
            # floating ip already atteched. do nothing
            logger.debug('Floating IP {} already attached to eth0'.format(fip))
        else:
            self.ibm_vpc_client.add_instance_network_interface_floating_ip(
                instance['id'], instance['network_interfaces'][0]['id'], fip_id)

    def get_instance_data(self):
        """
        Returns the instance information
        """
        instances_data = self.ibm_vpc_client.list_instances(name=self.name).get_result()
        if len(instances_data['instances']) > 0:
            self.instance_data = instances_data['instances'][0]
            return self.instance_data
        return None

    def get_instance_id(self):
        """
        Returns the instance ID
        """
        instance_data = self.get_instance_data()
        if instance_data:
            self.instance_id = instance_data['id']
            return self.instance_id

        logger.debug('VM instance {} does not exists'.format(self.name))
        return None

    def _get_ip_address(self):
        """
        Requests the the primary network IP address
        """
        ip_address = None
        if self.instance_id:
            while not ip_address or ip_address == '0.0.0.0':
                instance_data = self.ibm_vpc_client.get_instance(self.instance_id).get_result()
                ip_address = instance_data['primary_network_interface']['primary_ipv4_address']
        return ip_address

    def create(self, check_if_exists=False, start=True):
        """
        Creates a new VM instance
        """
        instance = None
        vsi_exists = True if self.instance_id else False

        if check_if_exists and not vsi_exists:
            logger.debug('Checking if VM instance {} already exists'.format(self.name))
            instances_data = self.get_instance_data()
            if instances_data:
                logger.debug('VM instance {} already exists'.format(self.name))
                vsi_exists = True
                self.instance_id = instances_data['id']

        if not vsi_exists:
            instance = self._create_instance()
            self.instance_id = instance['id']
            self.ip_address = self._get_ip_address()

        if self.public and instance:
            self._attach_floating_ip(instance)

        if start:
            # In IBM VPC, VM instances are automatically started on create
            if vsi_exists:
                self.start()

        return self.instance_id

    def start(self):
        logger.debug("Starting VM instance {}".format(self.name))

        try:
            resp = self.ibm_vpc_client.create_instance_action(self.instance_id, 'start')
        except ApiException as e:
            if e.code == 404:
                pass
            else:
                raise e

        logger.debug("VM instance {} started successfully".format(self.name))

    def _delete_instance(self):
        """
        Deletes the VM instacne and the associated volume
        """
        logger.debug("Deleting VM instance {}".format(self.name))
        try:
            self.ibm_vpc_client.delete_instance(self.instance_id)
        except ApiException as e:
            if e.code == 404:
                pass
            else:
                raise e
        self.instance_id = None
        self.ip_address = None
        self.del_ssh_client()

    def _stop_instance(self):
        """
        Stops the VM instacne and
        """
        logger.debug("Stopping VM instance {}".format(self.name))
        try:
            resp = self.ibm_vpc_client.create_instance_action(self.instance_id, 'stop')
        except ApiException as e:
            if e.code == 404:
                pass
            else:
                raise e

    def stop(self):
        if self.delete_on_dismantle:
            self._delete_instance()
        else:
            self._stop_instance()

    def delete(self):
        """
        Deletes the VM instance
        """
        self._delete_instance()
