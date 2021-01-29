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
import logging
from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException
from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG


logger = logging.getLogger(__name__)


class IBMVPCBackend:

    def __init__(self, ibm_vpc_config):
        logger.debug("Creating IBM VPC client")
        self.name = 'ibm_vpc'
        self.config = ibm_vpc_config

        self.endpoint = self.config['endpoint']
        self.vpc_name = self.config['vpc_name']
        self.region = self.endpoint.split('//')[1].split('.')[0]
        self.instances = []
        self.master = None

        iam_api_key = self.config.get('iam_api_key')
        self.custom_image = self.config.get('custom_lithops_image')

        authenticator = IAMAuthenticator(iam_api_key)
        self.ibm_vpc_client = VpcV1('2021-01-19', authenticator=authenticator)
        self.ibm_vpc_client.set_service_url(self.config['endpoint'] + '/v1')

        user_agent_string = 'ibm_vpc_{}'.format(self.config['user_agent'])
        self.ibm_vpc_client._set_user_agent_header(user_agent_string)

        msg = COMPUTE_CLI_MSG.format('IBM VPC')
        logger.info("{} - Region: {}".format(msg, self.region))

    def _create_vpc(self):
        """
        Creates a new VPC
        """
        if 'vpc_id' in self.config:
            return

        vpc_name = self.config['vpc_name']
        vpc_data = None

        assert re.match("^[a-z0-9-:-]*$", self.vpc_name),\
            'VPC name "{}" not valid'.format(self.vpc_name)

        vpcs_info = self.ibm_vpc_client.list_vpcs().get_result()
        for vpc in vpcs_info['vpcs']:
            if vpc['name'] == vpc_name:
                vpc_data = vpc

        if not vpc_data:
            logger.debug('Creating new VPC: {}'.format(vpc_name))
            vpc_prototype = {}
            vpc_prototype['address_prefix_management'] = 'auto'
            vpc_prototype['classic_access'] = False
            vpc_prototype['name'] = vpc_name
            vpc_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.ibm_vpc_client.create_vpc(**vpc_prototype)
            vpc_data = response.result

        self.config['vpc_id'] = vpc_data['id']
        self.config['security_group_id'] = vpc_data['default_security_group']['id']

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

    def _create_subnet(self):
        if 'subnet_id' in self.config:
            return
        subnet_name = 'lithops-subnet-{}'.format(self.vpc_name)
        subnet_data = None

        subnets_info = self.ibm_vpc_client.list_subnets(resource_group_id=self.config['resource_group_id']).get_result()
        for sn in subnets_info['subnets']:
            if sn['name'] == subnet_name:
                subnet_data = sn

        if not subnet_data:
            logger.debug('Creating new Subnet: {}'.format(subnet_name))
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

    def _create_floating_ip(self):
        """
        Creates a new floating IP address
        """
        if 'floating_ip_id' in self.config:
            return

        floating_ip_name = 'lithops-floatingip-{}'.format(self.vpc_name)
        floating_ip_data = None

        floating_ips_info = self.ibm_vpc_client.list_floating_ips().get_result()
        for fip in floating_ips_info['floating_ips']:
            if fip['name'] == floating_ip_name:
                floating_ip_data = fip

        if not floating_ip_data:
            logger.debug('Creating new floating IP: {}'.format(floating_ip_name))
            floating_ip_prototype = {}
            floating_ip_prototype['name'] = floating_ip_name
            floating_ip_prototype['zone'] = {'name': self.config['zone_name']}
            floating_ip_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.ibm_vpc_client.create_floating_ip(floating_ip_prototype)
            floating_ip_data = response.result

        self.config['floating_ip'] = floating_ip_data['address']
        self.config['floating_ip_id'] = floating_ip_data['id']

    def _create_gateway(self):
        """
        Crates a public gateway.
        Gateway is used by private nodes for accessing internet
        """
        if 'gateway_id' in self.config:
            return

        gateway_name = 'lithops-gateway-{}'.format(self.vpc_name)
        gateway_data = None

        gateways_info = self.ibm_vpc_client.list_public_gateways().get_result()
        for gw in gateways_info['public_gateways']:
            if gw['name'] == gateway_name:
                gateway_data = gw

        if not gateway_data:
            logger.debug('Creating new Gateway: {}'.format(gateway_name))
            gateway_prototype = {}
            gateway_prototype['vpc'] = {'id': self.config['vpc_id']}
            gateway_prototype['zone'] = {'name': self.config['zone_name']}
            gateway_prototype['name'] = gateway_name
            response = self.ibm_vpc_client.create_public_gateway(**gateway_prototype)
            gateway_data = response.result

        self.config['gateway_id'] = gateway_data['id']

    def init(self):
        """
        Initialize the VPC
        """
        logger.debug('Initializing IBM VPC backend')
        self._create_vpc()
        self._create_subnet()
        self._create_floating_ip()
        self._create_gateway()

    def get_instances(self):
        """
        Returns the list of all created VM instances
        """
        return self.instances

    def create_instance(self, name, master=False):
        """
        Create a new VM python instance
        This method does not create the physical VM.
        """
        vsi = IBMVPCInstance(name, self.config, self.ibm_vpc_client, master=master)
        if master:
            self.master = vsi
        self.instances.append(vsi)
        return vsi

    def dismantle(self):
        """
        Stop all VM instances
        """
        for instance in self.instances:
            logger.debug("Dismantle {} for {}"
                         .format(instance.get_instance_id(),
                                 instance.get_ip_address()))
            instance.stop()

    def clean(self):
        """
        Clan all the backend resources
        """
        pass

    def clear(self):
        """
        Clear all the backend resources
        """
        pass

    def get_runtime_key(self, runtime_name):
        name = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = '/'.join([self.name, name])
        return runtime_key


class IBMVPCInstance:

    def __init__(self, name, ibm_vpc_config, ibm_vpc_client, master=False):
        """
        Intialize a VM instance instance
        VMs can have master role, this means they will have a public IP address
        """
        self.name = name
        self.config = ibm_vpc_config
        self.ibm_vpc_client = ibm_vpc_client
        self.master = master
        self.instance_data = None
        self.ssh_client = None

        self.instance_id = self.config.get('instance_id')
        self.ip_address = self.config.get('floating_ip') if master else self.config.get('ip_address')

        self.vm_create_timeout = self.config.get('vm_create_timeout', 120)
        self.ssh_credentials = {'username': self.config.get('ssh_user', 'root'),
                                'password': self.config.get('ssh_password', None),
                                'key_filename': self.config.get('ssh_key_filename', None)}

    def get_name(self):
        """
        Returns the instance name
        """
        return self.name

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM only if the Instance is the master
        """
        if self.ip_address:
            if not self.ssh_client:
                self.ssh_client = SSHClient(self.get_ip_address(), self.ssh_credentials)
        return self.ssh_client

    def get_ip_address(self):
        """
        Return the internal private IP
        """
        return self.ip_address

    def get_instance_id(self):
        """
        Return the instance ID
        """
        return self.instance_id

    def _create_instance(self, instance_name):
        """
        Creates a new VM instance
        """
        logger.debug("Creating new VM instance: {}".format(instance_name))

        security_group_identity_model = {'id': self.config['security_group_id']}
        subnet_identity_model = {'id': self.config['subnet_id']}
        primary_network_interface = {
            'name': 'eth0',
            'subnet': subnet_identity_model,
            'security_groups': [security_group_identity_model]
        }

        boot_volume_profile = {
            'capacity': 100,
            'name': '{}-boot'.format(instance_name),
            'profile': {'name': self.config['volume_tier_name']}}

        boot_volume_attachment = {
            'delete_volume_on_instance_delete': True,
            'volume': boot_volume_profile
        }

        key_identity_model = {'id': self.config['key_id']}
        instance_prototype_model = {
            'keys': [key_identity_model],
            'name': '{}-instance'.format(instance_name),
        }

        instance_prototype_model['profile'] = {'name': self.config['profile_name']}
        instance_prototype_model['resource_group'] = {'id': self.config['resource_group_id']}
        instance_prototype_model['vpc'] = {'id': self.config['vpc_id']}
        instance_prototype_model['image'] = {'id': self.config['image_id']}
        instance_prototype_model['zone'] = {'name': self.config['zone_name']}
        instance_prototype_model['boot_volume_attachment'] = boot_volume_attachment
        instance_prototype_model['primary_network_interface'] = primary_network_interface

        try:
            resp = self.ibm_vpc_client.create_instance(instance_prototype_model)
        except ApiException as e:
            print("Create VM instance failed with status code " + str(e.code) + ": " + e.message)
            raise e

        logger.debug("VM instance {} created successfully ".format(instance_name))

        return resp.result

    def _attach_floating_ip(self, instance):

        fip = self.config['floating_ip']
        fip_id = self.config['floating_ip_id']

        logger.debug('Attaching floating IP {} to VM instance {}'.format(fip, instance['id']))

        # we need to check if floating ip is not attached already. if not, attach it to instance
        instance_primary_ni = instance['primary_network_interface']

        if instance_primary_ni['primary_ipv4_address'] and instance_primary_ni['id'] == fip_id:
            # floating ip already atteched. do nothing
            logger.debug('Floating IP {} already attached to eth0'.format(fip))
        else:
            self.ibm_vpc_client.add_instance_network_interface_floating_ip(
                instance['id'], instance['network_interfaces'][0]['id'], fip_id)

    def _get_instance_id_and_status(self, name):
        # check if VSI exists and return it's id with status
        all_instances = self.ibm_vpc_client.list_instances().get_result()['instances']
        for instance in all_instances:
            if instance['name'] == name:
                logger.debug('{}  exists'.format(instance['name']))
                return instance['id'], instance['status']

    def is_running(self):
        """
        Checks if the VM instance is in running status
        """
        resp = self.ibm_vpc_client.get_instance(self.instance_id).get_result()
        if resp['status'] == 'running':
            return True
        return False

    def create(self, check_if_exists=False, start=True):
        """
        Creates a new VM instance
        """
        vsi_exists = False

        if check_if_exists:
            logger.debug('Checking if VM {} already exists'.format(self.name))
            instances_info = self.ibm_vpc_client.list_instances().get_result()
            for instance in instances_info['instances']:
                if instance['name'] == '{}-instance'.format(self.name):
                    logger.debug('VM {} already exists'.format(self.name))
                    vsi_exists = True
                    self.instance_id = instance['id']
                    break

        if not vsi_exists:
            instance = self._create_instance(self.name)
            self.instance_id = instance['id']
            self.config['instance_id'] = self.instance_id

        # Only the master node has public floating ip
        if self.master:
            self._attach_floating_ip(instance)

        if start:
            logger.info("Starting VM instance {}".format(self.instance_id))
            # In IBM VPC, VM instances are automatically started on create
            if vsi_exists:
                self.start()

        return self.instance_id

    def start(self):
        logger.info("Starting VM instance id {}".format(self.instance_id))

        try:
            resp = self.ibm_vpc_client.create_instance_action(self.instance_id, 'start')
        except ApiException as e:
            print("Start VM instance failed with status code " + str(e.code) + ": " + e.message)
            raise e

        logger.debug("VM instance {} started successfully".format(self.instance_id))

    def _delete_instance(self):
        """
        Deletes the VM instacne and the associated volume
        """
        logger.debug("Deleting VM instance {}".format(self.instance_id))
        try:
            resp = self.ibm_vpc_client.delete_instance(self.instance_id)
        except ApiException as e:
            print("Deleting VM instance failed with status code " + str(e.code) + ": " + e.message)
            raise e
        logger.debug("VM instance {} deleted".format(self.instance_id))

    def _stop_instance(self):
        """
        Stops the VM instacne and
        """
        logger.debug("Stopping VM instance {}".format(self.instance_id))
        try:
            resp = self.ibm_vpc_client.create_instance_action(self.instance_id, 'stop')
        except ApiException as e:
            print("Stopping VM instance failed with status code " + str(e.code) + ": " + e.message)
            raise e
        logger.debug("VM instance {} stopped".format(self.instance_id))

    def stop(self):
        if self.config['delete_on_dismantle'] and not self.master:
            self._delete_instance()
        else:
            self._stop_instance()
