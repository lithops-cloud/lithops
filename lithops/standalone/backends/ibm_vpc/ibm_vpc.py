#
# (C) Copyright Cloudlab URV 2020
# (C) Copyright IBM Corp. 2023
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

import functools
import inspect
import re
import os
import paramiko
import time
import logging
import uuid
from datetime import datetime
from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException
from concurrent.futures import ThreadPoolExecutor

from lithops.version import __version__
from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR, SA_IMAGE_NAME_DEFAULT
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import CLOUD_CONFIG_WORKER, CLOUD_CONFIG_WORKER_PK, ExecMode, get_host_setup_script
from lithops.standalone.standalone import LithopsValidationError

logger = logging.getLogger(__name__)

INSTANCE_START_TIMEOUT = 180
VPC_API_VERSION = '2021-09-21'


class IBMVPCBackend:

    def __init__(self, config, mode):
        logger.debug("Creating IBM VPC client")
        self.name = 'ibm_vpc'
        self.config = config
        self.mode = mode

        self.vpc_data = {}
        self.vpc_name = None
        self.vpc_key = None

        self.vpc_data_type = 'provided' if 'vpc_id' in self.config else 'created'
        self.ssh_data_type = 'provided' if 'ssh_key_id' in self.config else 'created'

        self.endpoint = self.config['endpoint']
        self.region = self.config['region']
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, self.region + '_data')
        self.custom_image = self.config.get('custom_lithops_image')

        logger.debug(f'Setting VPC endpoint to: {self.endpoint}')

        self.master = None
        self.workers = []

        self.iam_api_key = self.config.get('iam_api_key')
        authenticator = IAMAuthenticator(self.iam_api_key, url=self.config.get('iam_endpoint'))
        self.vpc_cli = VpcV1(VPC_API_VERSION, authenticator=authenticator)
        self.vpc_cli.set_service_url(self.config['endpoint'] + '/v1')

        user_agent_string = 'ibm_vpc_{}'.format(self.config['user_agent'])
        self.vpc_cli._set_user_agent_header(user_agent_string)

        # decorate instance public methods with except/retry logic
        decorate_instance(self.vpc_cli, vpc_retry_on_except)

        msg = COMPUTE_CLI_MSG.format('IBM VPC')
        logger.info(f"{msg} - Region: {self.region}")

    def _load_vpc_data(self):
        """
        Loads VPC data from local cache
        """
        self.vpc_data = load_yaml_config(self.cache_file)

        if self.vpc_data:
            logger.debug(f'VPC data loaded from {self.cache_file}')

        if 'vpc_id' in self.vpc_data:
            self.vpc_key = self.vpc_data['vpc_id'][-6:]
            self.vpc_name = self.vpc_data['vpc_name']

        return self.vpc_data

    def _dump_vpc_data(self):
        """
        Dumps VPC data to local cache
        """
        dump_yaml_config(self.cache_file, self.vpc_data)

    def _create_vpc(self):
        """
        Creates a new VPC
        """
        if 'vpc_id' in self.config:
            return

        if 'vpc_id' in self.vpc_data:
            try:
                self.vpc_cli.get_vpc(self.vpc_data['vpc_id'])
                self.config['vpc_id'] = self.vpc_data['vpc_id']
                self.config['security_group_id'] = self.vpc_data['security_group_id']
                return
            except ApiException:
                pass

        vpc_info = None

        iam_id = self.iam_api_key[:4].lower()
        self.vpc_name = self.config.get('vpc_name', f'lithops-vpc-{iam_id}-{str(uuid.uuid4())[-6:]}')
        logger.debug(f'Setting VPC name to: {self.vpc_name}')

        assert re.match("^[a-z0-9-:-]*$", self.vpc_name),\
            f'VPC name "{self.vpc_name}" not valid'

        vpcs_info = self.vpc_cli.list_vpcs().get_result()
        for vpc in vpcs_info['vpcs']:
            if vpc['name'] == self.vpc_name:
                vpc_info = vpc

        if not vpc_info:
            logger.debug(f'Creating VPC {self.vpc_name}')
            vpc_prototype = {}
            vpc_prototype['address_prefix_management'] = 'auto'
            vpc_prototype['classic_access'] = False
            vpc_prototype['name'] = self.vpc_name
            vpc_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.vpc_cli.create_vpc(**vpc_prototype)
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

        sg_rules = self.vpc_cli.get_security_group(self.config['security_group_id'])
        for rule in sg_rules.get_result()['rules']:
            if all(item in rule.items() for item in sg_rule_prototype_ssh.items()):
                deloy_ssh_rule = False
            if all(item in rule.items() for item in sg_rule_prototype_icmp.items()):
                deploy_icmp_rule = False

        if deloy_ssh_rule:
            self.vpc_cli.create_security_group_rule(
                self.config['security_group_id'],
                sg_rule_prototype_ssh
            )
        if deploy_icmp_rule:
            self.vpc_cli.create_security_group_rule(
                self.config['security_group_id'],
                sg_rule_prototype_icmp
            )

    def _create_ssh_key(self):

        if 'ssh_key_id' in self.config:
            return

        if 'ssh_key_id' in self.vpc_data:
            try:
                self.vpc_cli.get_key(self.vpc_data['ssh_key_id'])
                self.config['ssh_key_id'] = self.vpc_data['ssh_key_id']
                self.config['ssh_key_filename'] = self.vpc_data['ssh_key_filename']
                return
            except ApiException:
                pass

        keyname = f'lithops-key-{str(uuid.uuid4())[-8:]}'
        filename = os.path.join("~", ".ssh", f"{keyname}.{self.name}.id_rsa")
        key_filename = os.path.expanduser(filename)

        key_info = None

        def _get_ssh_key():
            for key in self.vpc_cli.list_keys().result["keys"]:
                if key["name"] == keyname:
                    return key

        if not os.path.isfile(key_filename):
            logger.debug("Generating new ssh key pair")
            os.system(f'ssh-keygen -b 2048 -t rsa -f {key_filename} -q -N ""')
            logger.debug(f"SHH key pair generated: {key_filename}")
        else:
            key_info = _get_ssh_key()

        if not key_info:
            with open(f"{key_filename}.pub", "r") as file:
                ssh_key_data = file.read()
            try:
                key_info = self.vpc_cli.create_key(
                    public_key=ssh_key_data, name=keyname, type="rsa",
                    resource_group={"id": self.config['resource_group_id']}
                ).get_result()
            except ApiException as e:
                logger.error(e)
                if "Key with name already exists" in e.message:
                    self.vpc_cli.delete_key(id=_get_ssh_key()["id"])
                    key_info = self.vpc_cli.create_key(
                        public_key=ssh_key_data, name=keyname, type="rsa",
                        resource_group={"id": self.config['resource_group_id']},
                    ).get_result()
                else:
                    if "Key with fingerprint already exists" in e.message:
                        logger.error("Can't register an SSH key with the same fingerprint")
                    raise e  # can't continue the configuration process without a valid ssh key

        self.config['ssh_key_id'] = key_info["id"]
        self.config['ssh_key_filename'] = key_filename

    def _create_subnet(self):
        """
        Creates a new subnet
        """
        if 'subnet_id' in self.config:
            if 'subnet_id' in self.vpc_data and self.vpc_data['subnet_id'] == self.config['subnet_id']:
                self.config['zone_name'] = self.vpc_data['zone_name']
            else:
                resp = self.vpc_cli.get_subnet(self.config['subnet_id'])
                self.config['zone_name'] = resp.result['zone']['name']
            return

        if 'subnet_id' in self.vpc_data:
            try:
                self.vpc_cli.get_subnet(self.vpc_data['subnet_id'])
                self.config['subnet_id'] = self.vpc_data['subnet_id']
                self.config['zone_name'] = self.vpc_data['zone_name']
                return
            except ApiException:
                pass

        subnet_name = f'lithops-subnet-{self.vpc_key}'
        subnet_data = None

        subnets_info = self.vpc_cli.list_subnets(resource_group_id=self.config['resource_group_id']).get_result()
        for sn in subnets_info['subnets']:
            if sn['name'] == subnet_name:
                subnet_data = sn

        if not subnet_data:
            logger.debug(f'Creating Subnet {subnet_name}')
            subnet_prototype = {}
            subnet_prototype['zone'] = {'name': self.region + '-1'}
            subnet_prototype['ip_version'] = 'ipv4'
            subnet_prototype['name'] = subnet_name
            subnet_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            subnet_prototype['vpc'] = {'id': self.config['vpc_id']}
            subnet_prototype['total_ipv4_address_count'] = 256
            response = self.vpc_cli.create_subnet(subnet_prototype)
            subnet_data = response.result

        self.config['subnet_id'] = subnet_data['id']
        self.config['zone_name'] = subnet_data['zone']['name']

    def _create_gateway(self):
        """
        Crates a public gateway.
        Gateway is used by private nodes for accessing internet
        """
        if 'gateway_id' in self.config:
            return

        if 'gateway_id' in self.vpc_data:
            try:
                self.vpc_cli.get_public_gateway(self.vpc_data['gateway_id'])
                self.config['gateway_id'] = self.vpc_data['gateway_id']
                return
            except ApiException:
                pass

        gateway_name = f'lithops-gateway-{self.vpc_key}'
        gateway_data = None

        gateways_info = self.vpc_cli.list_public_gateways().get_result()
        for gw in gateways_info['public_gateways']:
            if gw['vpc']['id'] == self.config['vpc_id']:
                gateway_data = gw

        if not gateway_data:
            logger.debug(f'Creating Gateway {gateway_name}')
            fip, fip_id = self._get_or_create_floating_ip()
            gateway_prototype = {}
            gateway_prototype['vpc'] = {'id': self.config['vpc_id']}
            gateway_prototype['zone'] = {'name': self.config['zone_name']}
            gateway_prototype['name'] = gateway_name
            gateway_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            gateway_prototype['floating_ip'] = {'id': fip_id}
            response = self.vpc_cli.create_public_gateway(**gateway_prototype)
            gateway_data = response.result

        self.config['gateway_id'] = gateway_data['id']

        # Attach public gateway to the subnet
        self.vpc_cli.set_subnet_public_gateway(
            self.config['subnet_id'], {'id': self.config['gateway_id']})

    def _get_or_create_floating_ip(self):
        """
        Creates a new floating IP address
        """
        fip_data = None

        floating_ips_info = self.vpc_cli.list_floating_ips().get_result()
        for fip in floating_ips_info['floating_ips']:
            if fip['name'].startswith("lithops-recyclable") and 'target' not in fip:
                fip_data = fip

        if not fip_data:
            floating_ip_name = f'lithops-recyclable-{str(uuid.uuid4())[-4:]}'
            logger.debug(f'Creating floating IP {floating_ip_name}')
            floating_ip_prototype = {}
            floating_ip_prototype['name'] = floating_ip_name
            floating_ip_prototype['zone'] = {'name': self.config['zone_name']}
            floating_ip_prototype['resource_group'] = {'id': self.config['resource_group_id']}
            response = self.vpc_cli.create_floating_ip(floating_ip_prototype)
            fip_data = response.result

        return fip_data['address'], fip_data['id']

    def _create_master_floating_ip(self):
        """
        Creates the master VM floating IP address
        """
        if 'floating_ip_id' in self.config:
            return

        if 'floating_ip_id' in self.vpc_data:
            try:
                self.vpc_cli.get_floating_ip(self.vpc_data['floating_ip_id'])
                self.config['floating_ip'] = self.vpc_data['floating_ip']
                self.config['floating_ip_id'] = self.vpc_data['floating_ip_id']
                return
            except ApiException:
                pass

        if 'floating_ip_id' not in self.config:
            fip, fip_id = self._get_or_create_floating_ip()
            self.config['floating_ip'] = fip
            self.config['floating_ip_id'] = fip_id

    def _request_image_id(self):
        """
        Requests the Ubuntu Image ID
        """
        if 'image_id' in self.config:
            return

        images_def = self.vpc_cli.list_images().result['images']
        images_user = self.vpc_cli.list_images(resource_group_id=self.config['resource_group_id']).result['images']
        images_def.extend(images_user)

        if 'image_id' in self.vpc_data:
            for image in images_def:
                if image['id'] == self.vpc_data['image_id'] and \
                   not image['name'].startswith('ibm-ubuntu-22'):
                    self.config['image_id'] = self.vpc_data['image_id']
                    break

        if 'image_id' not in self.config:
            for image in images_def:
                if image['name'] == SA_IMAGE_NAME_DEFAULT:
                    logger.debug(f"Found default VM image: {SA_IMAGE_NAME_DEFAULT}")
                    self.config['image_id'] = image['id']
                    break

        if 'image_id' not in self.config:
            for image in images_def:
                if image['name'].startswith('ibm-ubuntu-22') \
                   and "amd64" in image['name']:
                    self.config['image_id'] = image['id']
                    break

    def _create_master_instance(self):
        """
        Creates the master VM insatnce
        """
        name = self.config.get('master_name') or f'lithops-master-{self.vpc_key}'
        self.master = IBMVPCInstance(name, self.config, self.vpc_cli, public=True)
        self.master.public_ip = self.config['floating_ip']
        self.master.instance_id = self.config['instance_id'] if self.mode == ExecMode.CONSUME.value else None
        self.master.profile_name = self.config['master_profile_name']
        self.master.delete_on_dismantle = False
        self.master.ssh_credentials.pop('password')

    def init(self):
        """
        Initialize the VPC
        """
        logger.debug(f'Initializing IBM VPC backend ({self.mode} mode)')

        self._load_vpc_data()
        if self.mode != self.vpc_data.get('mode'):
            self.vpc_data = {}

        if self.mode == ExecMode.CONSUME.value:

            ins_id = self.config['instance_id']
            if not self.vpc_data or ins_id != self.vpc_data.get('instance_id'):
                name = self.vpc_cli.get_instance(ins_id).get_result()['name']
                self.config['master_name'] = name

            # Create the master VM instance
            self._create_master_instance()

            self.vpc_data = {
                'mode': self.mode,
                'vpc_data_type': 'provided',
                'ssh_data_type': 'provided',
                'master_name': self.master.name,
                'master_id': self.master.instance_id,
                'floating_ip': self.master.public_ip
            }

        elif self.mode in [ExecMode.CREATE.value, ExecMode.REUSE.value]:

            # Create the VPC if not exists
            self._create_vpc()

            # Set the suffix used for the VPC resources
            self.vpc_key = self.config['vpc_id'][-6:]

            # Create the ssh key pair if not exists
            self._create_ssh_key()
            # Create a new subnaet if not exists
            self._create_subnet()
            # Create a new gateway if not exists
            self._create_gateway()
            # Create the master VM floating IP address
            self._create_master_floating_ip()
            # Requests the Ubuntu image ID
            self._request_image_id()

            # Create the master VM instance
            self._create_master_instance()

            self.vpc_data = {
                'mode': self.mode,
                'vpc_data_type': self.vpc_data_type,
                'ssh_data_type': self.ssh_data_type,
                'master_name': self.master.name,
                'master_id': self.vpc_key,
                'vpc_name': self.vpc_name,
                'vpc_id': self.config['vpc_id'],
                'subnet_id': self.config['subnet_id'],
                'security_group_id': self.config['security_group_id'],
                'floating_ip': self.config['floating_ip'],
                'floating_ip_id': self.config['floating_ip_id'],
                'gateway_id': self.config['gateway_id'],
                'zone_name': self.config['zone_name'],
                'image_id': self.config['image_id'],
                'ssh_key_id': self.config['ssh_key_id'],
                'ssh_key_filename': self.config['ssh_key_filename']
            }

        self._dump_vpc_data()

    def build_image(self, image_name, script_file, overwrite, extra_args=[]):
        """
        Builds a new VM Image
        """
        images = self.vpc_cli.list_images(name=image_name, resource_group_id=self.config['resource_group_id']).result['images']
        if len(images) > 0:
            image_id = images[0]['id']
            if overwrite:
                logger.debug(f"Deleting existing VM Image '{image_name}'")
                self.vpc_cli.delete_image(id=image_id)
                while len(self.vpc_cli.list_images(name=image_name, resource_group_id=self.config['resource_group_id']).result['images']) > 0:
                    time.sleep(2)
            else:
                raise Exception(f"The image with name '{image_name}' already exists with ID: '{image_id}'."
                                " Use '--overwrite' or '-o' if you want ot overwrite it")

        initial_vpc_data = self._load_vpc_data()

        self.init()

        fip, fip_id = self._get_or_create_floating_ip()
        self.config['floating_ip'] = fip
        self.config['floating_ip_id'] = fip_id

        build_vm = IBMVPCInstance(image_name, self.config, self.vpc_cli, public=True)
        build_vm.public_ip = self.config['floating_ip']
        build_vm.profile_name = self.config['master_profile_name']
        build_vm.delete_on_dismantle = False
        build_vm.create()
        build_vm.wait_ready()

        logger.debug(f"Uploading installation script to {build_vm}")
        remote_script = "/tmp/install_lithops.sh"
        script = get_host_setup_script()
        build_vm.get_ssh_client().upload_data_to_file(script, remote_script)
        logger.debug("Executing installation script. Be patient, this process can take up to 3 minutes")
        build_vm.get_ssh_client().run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};")
        logger.debug("Installation script finsihed")

        if script_file:
            script = os.path.expanduser(script_file)
            logger.debug(f"Uploading user script {script_file} to {build_vm}")
            remote_script = "/tmp/install_user_lithops.sh"
            build_vm.get_ssh_client().upload_local_file(script, remote_script)
            logger.debug("Executing user script. Be patient, this process can take long")
            build_vm.get_ssh_client().run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};")
            logger.debug("User script finsihed")

        build_vm.stop()
        build_vm.wait_stopped()

        vm_data = build_vm.get_instance_data()
        volume_id = vm_data['boot_volume_attachment']['volume']['id']

        image_prototype = {}
        image_prototype['name'] = image_name
        image_prototype['source_volume'] = {'id': volume_id}
        image_prototype['resource_group'] = {'id': self.config['resource_group_id']}
        self.vpc_cli.create_image(image_prototype)

        logger.debug("Be patient, VM imaging can take up to 6 minutes")

        while True:
            images = self.vpc_cli.list_images(name=image_name, resource_group_id=self.config['resource_group_id']).result['images']
            if len(images) > 0:
                logger.debug(f"VM Image is being created. Current status: {images[0]['status']}")
                if images[0]['status'] == 'available':
                    break
            time.sleep(30)

        build_vm.delete()

        if not initial_vpc_data:
            self.clean(all)

        logger.info(f"VM Image created. Image ID: {images[0]['id']}")

    def list_images(self):
        """
        List VM Images
        """
        images_def = self.vpc_cli.list_images().result['images']
        images_user = self.vpc_cli.list_images(resource_group_id=self.config['resource_group_id']).result['images']
        images_def.extend(images_user)

        result = set()

        for img in images_def:
            if img['operating_system']['family'] == 'Ubuntu Linux':
                opsys = img['operating_system']['display_name']
                image_name = img['name']
                image_id = img['id']
                created_at = datetime.strptime(img['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
                if '22' in opsys:
                    result.add((image_name, image_id, created_at))

        return sorted(result, key=lambda x: x[2], reverse=True)

    def _delete_vm_instances(self, all=False):
        """
        Deletes all VM instances in the VPC
        """
        msg = (f'Deleting all Lithops worker VMs from {self.vpc_name}'
               if self.vpc_name else 'Deleting all Lithops worker VMs')
        logger.info(msg)

        def delete_instance(instance_info):
            ins_name, ins_id = instance_info
            try:
                logger.debug(f'Deleting instance {ins_name}')
                self.vpc_cli.delete_instance(ins_id)
            except ApiException as err:
                if err.code == 404:
                    pass
                else:
                    raise err

        vms_prefixes = ('lithops-worker', 'lithops-master') if all else ('lithops-worker',)

        def get_instances():
            instances = set()
            instances_info = self.vpc_cli.list_instances().get_result()
            for ins in instances_info['instances']:
                if ins['name'].startswith(vms_prefixes) \
                   and ins['vpc']['id'] == self.vpc_data['vpc_id']:
                    instances.add((ins['name'], ins['id']))
            return instances

        deleted_instances = set()
        while True:
            instances_to_delete = set()
            for ins_to_delete in get_instances():
                if ins_to_delete not in deleted_instances:
                    instances_to_delete.add(ins_to_delete)

            if instances_to_delete:
                with ThreadPoolExecutor(len(instances_to_delete)) as executor:
                    executor.map(delete_instance, instances_to_delete)
                deleted_instances.update(instances_to_delete)
            else:
                break

        master_pk = os.path.join(self.cache_dir, f"{self.vpc_data['master_name']}-id_rsa.pub")
        if os.path.isfile(master_pk):
            os.remove(master_pk)

        if self.vpc_data['vpc_data_type'] == 'provided':
            return

        # Wait until all instances are deleted
        while get_instances():
            time.sleep(1)

    def _delete_subnet(self):
        """
        Deletes all VM instances in the VPC
        """
        subnet_name = f'lithops-subnet-{self.vpc_key}'
        if 'subnet_id' in self.vpc_data:
            logger.debug(f'Deleting subnet {subnet_name}')

            try:
                self.vpc_cli.unset_subnet_public_gateway(self.vpc_data['subnet_id'])
            except ApiException as err:
                if err.code == 404 or err.code == 400:
                    logger.debug(err)
                else:
                    raise err

            try:
                self.vpc_cli.delete_subnet(self.vpc_data['subnet_id'])
            except ApiException as err:
                if err.code == 404 or err.code == 400:
                    logger.debug(err)
                else:
                    raise err

    def _delete_gateway(self):
        """
        Deletes the public gateway
        """
        gateway_name = f'lithops-gateway-{self.vpc_key}'
        if 'gateway_id' in self.vpc_data:
            logger.debug(f'Deleting gateway {gateway_name}')
            try:
                self.vpc_cli.delete_public_gateway(self.vpc_data['gateway_id'])
            except ApiException as err:
                if err.code == 404 or err.code == 400:
                    logger.debug(err)
                else:
                    raise err

    def _delete_vpc(self):
        """
        Deletes the VPC
        """
        if self.vpc_data['vpc_data_type'] == 'provided':
            return

        msg = (f'Deleting all Lithops VPC resources from {self.vpc_name}')
        logger.info(msg)

        self._delete_subnet()
        self._delete_gateway()

        if 'vpc_id' in self.vpc_data:
            logger.debug(f'Deleting VPC {self.vpc_data["vpc_name"]}')
            try:
                self.vpc_cli.delete_vpc(self.vpc_data['vpc_id'])
            except ApiException as err:
                if err.code == 404 or err.code == 400:
                    logger.debug(err)
                else:
                    raise err

    def _delete_ssh_key(self):
        """
        Deletes the ssh key
        """
        if self.vpc_data['ssh_data_type'] == 'provided':
            return

        key_filename = self.vpc_data['ssh_key_filename']
        if "lithops-key-" in key_filename:
            if os.path.isfile(key_filename):
                os.remove(key_filename)
            if os.path.isfile(f"{key_filename}.pub"):
                os.remove(f"{key_filename}.pub")

        if 'ssh_key_id' in self.vpc_data:
            keyname = key_filename.split('/')[-1].split('.')[0]
            logger.debug(f'Deleting SSH key {keyname}')
            try:
                self.vpc_cli.delete_key(id=self.vpc_data['ssh_key_id'])
            except ApiException as err:
                if err.code == 404 or err.code == 400:
                    logger.debug(err)
                else:
                    raise err

    def clean(self, all=False):
        """
        Clean all the backend resources
        The gateway public IP and the floating IP are never deleted
        """
        logger.info('Cleaning IBM VPC resources')

        self._load_vpc_data()

        if not self.vpc_data:
            return

        if self.vpc_data['mode'] == ExecMode.CONSUME.value:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        else:
            self._delete_vm_instances(all=all)
            self._delete_vpc() if all else None
            self._delete_ssh_key() if all else None
            if all and os.path.exists(self.cache_file):
                os.remove(self.cache_file)

    def clear(self, job_keys=None):
        """
        Delete all the workers
        """
        # clear() is automatically called after get_result()
        self.dismantle(include_master=False)

    def dismantle(self, include_master=True):
        """
        Stop all worker VM instances
        """
        if len(self.workers) > 0:
            with ThreadPoolExecutor(min(len(self.workers), 48)) as ex:
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
        instance = IBMVPCInstance(name, self.config, self.vpc_cli)

        for key in kwargs:
            if hasattr(instance, key):
                setattr(instance, key, kwargs[key])

        return instance

    def create_worker(self, name):
        """
        Creates a new worker VM instance
        """
        worker = IBMVPCInstance(name, self.config, self.vpc_cli, public=False)

        user = worker.ssh_credentials['username']

        pub_key = f'{self.cache_dir}/{self.master.name}-id_rsa.pub'
        if os.path.isfile(pub_key):
            with open(pub_key, 'r') as pk:
                pk_data = pk.read().strip()
            user_data = CLOUD_CONFIG_WORKER_PK.format(user, pk_data)
            worker.ssh_credentials['key_filename'] = '~/.ssh/id_rsa'
            worker.ssh_credentials.pop('password')
        else:
            worker.ssh_credentials.pop('key_filename')
            token = worker.ssh_credentials['password']
            user_data = CLOUD_CONFIG_WORKER.format(user, token)

        worker.create(user_data=user_data)
        self.workers.append(worker)

    def get_runtime_key(self, runtime_name, version=__version__):
        """
        Creates the runtime key
        """
        name = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = os.path.join(self.name, version, self.vpc_data['master_id'], name)
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
        self.profile_name = self.config['worker_profile_name']

        self.vpc_cli = ibm_vpc_client or self._create_vpc_client()
        self.public = public

        self.ssh_client = None
        self.instance_id = None
        self.instance_data = None
        self.private_ip = None
        self.public_ip = None
        self.home_dir = '/root'

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', '~/.ssh/id_rsa')
        }
        self.validated = False

    def __str__(self):
        ip = self.public_ip if self.public else self.private_ip

        if ip is None or ip == '0.0.0.0':
            return f'VM instance {self.name}'
        else:
            return f'VM instance {self.name} ({ip})'

    def _create_vpc_client(self):
        """
        Creates an IBM VPC python-sdk instance
        """
        authenticator = IAMAuthenticator(self.config.get('iam_api_key'), url=self.config.get('iam_endpoint'))
        ibm_vpc_client = VpcV1(VPC_API_VERSION, authenticator=authenticator)
        ibm_vpc_client.set_service_url(self.config['endpoint'] + '/v1')

        # decorate instance public methods with except/retry logic
        decorate_instance(self.vpc_cli, vpc_retry_on_except)

        return ibm_vpc_client

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM
        """

        if not self.validated and self.public and self.instance_id:
            # validate that private ssh key in ssh_credentials is a pair of public key on instance
            key_filename = self.ssh_credentials['key_filename']
            key_filename = os.path.abspath(os.path.expanduser(key_filename))

            if not os.path.exists(key_filename):
                raise LithopsValidationError(f"Private key file {key_filename} doesn't exist")

            initialization_data = self.vpc_cli.get_instance_initialization(self.instance_id).get_result()

            private_res = paramiko.RSAKey(filename=key_filename).get_base64()
            key = None
            names = []
            for k in initialization_data['keys']:
                public_res = self.vpc_cli.get_key(k['id']).get_result()['public_key'].split(' ')[1]
                if public_res == private_res:
                    self.validated = True
                    break
                else:
                    names.append(k['name'])

            if not self.validated:
                raise LithopsValidationError(
                    f"No public key from keys: {names} on master {self} not a pair for private ssh key {key_filename}")

        if not self.ssh_client:
            if self.public and self.public_ip:
                self.ssh_client = SSHClient(self.public_ip, self.ssh_credentials)
            elif self.private_ip:
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

    def _create_instance(self, user_data):
        """
        Creates a new VM instance
        """
        logger.debug(f"Creating new VM instance {self.name}")

        security_group_identity_model = {'id': self.config['security_group_id']}
        subnet_identity_model = {'id': self.config['subnet_id']}
        primary_network_interface = {
            'name': 'eth0',
            'subnet': subnet_identity_model,
            'security_groups': [security_group_identity_model]
        }

        boot_volume_data = {
            'capacity': self.config['boot_volume_capacity'],
            'name': f'{self.name}-{str(uuid.uuid4())[:4]}-boot',
            'profile': {'name': self.config['boot_volume_profile']}}

        boot_volume_attachment = {
            'delete_volume_on_instance_delete': True,
            'volume': boot_volume_data
        }

        key_identity_model = {'id': self.config['ssh_key_id']}

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

        if user_data:
            instance_prototype['user_data'] = user_data

        try:
            resp = self.vpc_cli.create_instance(instance_prototype)
        except ApiException as err:
            if err.code == 400 and 'already exists' in err.message:
                return self.get_instance_data()
            elif err.code == 400 and 'over quota' in err.message:
                logger.debug(f"Create VM instance {self.name} failed due to quota limit")
            else:
                logger.debug("Create VM instance {} failed with status code {}: {}"
                             .format(self.name, str(err.code), err.message))
            raise err

        self.instance_data = resp.result
        self.instance_id = self.instance_data['id']

        logger.debug(f"VM instance {self.name} created successfully")

        return self.instance_data

    def _attach_floating_ip(self, instance):
        """
        Attach a floating IP address only if the VM is the master instance
        """

        fip = self.config['floating_ip']
        fip_id = self.config['floating_ip_id']

        logger.debug(f"Attaching floating IP {fip} to {self}")

        # we need to check if floating ip is not attached already. if not, attach it to instance
        instance_primary_ni = instance['primary_network_interface']

        if instance_primary_ni['primary_ipv4_address'] and instance_primary_ni['id'] == fip_id:
            # floating ip already atteched. do nothing
            logger.debug(f'Floating IP {fip} already attached to eth0')
        else:
            self.vpc_cli.add_instance_network_interface_floating_ip(
                instance['id'], instance['network_interfaces'][0]['id'], fip_id)

    def get_instance_data(self):
        """
        Returns the instance information
        """
        instances_data = self.vpc_cli.list_instances(name=self.name).get_result()
        if len(instances_data['instances']) > 0:
            self.instance_data = instances_data['instances'][0]
            self.instance_id = self.instance_data['id']

        return self.instance_data

    def get_instance_id(self):
        """
        Returns the instance ID
        """
        if not self.instance_id and self.instance_data:
            self.instance_id = self.instance_data['id']

        if not self.instance_id:
            instance_data = self.get_instance_data()
            if instance_data:
                self.instance_id = instance_data['id']
            else:
                logger.debug(f'VM instance {self.name} does not exists')

        return self.instance_id

    def get_private_ip(self):
        """
        Requests the private IP address
        """
        if not self.private_ip and self.instance_data:
            self.private_ip = self.instance_data['primary_network_interface']['primary_ipv4_address']

        while not self.private_ip or self.private_ip == '0.0.0.0':
            instance_data = self.get_instance_data()
            private_ip = instance_data['primary_network_interface']['primary_ipv4_address']
            if private_ip != '0.0.0.0':
                self.private_ip = private_ip
            else:
                time.sleep(1)

        return self.private_ip

    def get_public_ip(self):
        """
        Requests the public IP address
        """
        if not self.public:
            return None

        return self.public_ip

    def create(self, check_if_exists=False, user_data=None):
        """
        Creates a new VM instance
        """
        instance = None
        vsi_exists = True if self.instance_id else False

        if check_if_exists and not vsi_exists:
            logger.debug(f'Checking if VM instance {self.name} already exists')
            instances_data = self.get_instance_data()
            if instances_data:
                logger.debug(f'VM instance {self.name} already exists')
                vsi_exists = True

        instance = self._create_instance(user_data=user_data) if not vsi_exists else self.start()

        if instance and self.public:
            self._attach_floating_ip(instance)

        return self.instance_id

    def start(self):
        """
        Starts the VM instance
        """
        logger.debug(f"Starting VM instance {self.name}")

        try:
            self.vpc_cli.create_instance_action(self.instance_id, 'start')
        except ApiException as err:
            if err.code == 404:
                pass
            else:
                raise err

        logger.debug(f"VM instance {self.name} started successfully")

    def _delete_instance(self):
        """
        Deletes the VM instacne and the associated volume
        """
        logger.debug(f"Deleting VM instance {self.name}")
        try:
            self.vpc_cli.delete_instance(self.instance_id)
        except ApiException as err:
            if err.code == 404:
                pass
            else:
                raise err

        self.instance_data = None
        self.instance_id = None
        self.private_ip = None
        self.del_ssh_client()

    def is_stopped(self):
        """
        Checks if the VM instance is stoped
        """
        data = self.get_instance_data()
        if data['status'] == 'stopped':
            return True
        return False

    def wait_stopped(self, timeout=INSTANCE_START_TIMEOUT):
        """
        Waits until the VM instance is stoped
        """
        logger.debug(f'Waiting {self} to become stopped')

        start = time.time()

        while (time.time() - start < timeout):
            if self.is_stopped():
                return True
            time.sleep(3)

        raise TimeoutError(f'Stop probe expired on {self}')

    def _stop_instance(self):
        """
        Stops the VM instance
        """
        logger.debug(f"Stopping VM instance {self.name}")
        try:
            self.vpc_cli.create_instance_action(self.instance_id, 'stop')
        except ApiException as err:
            if err.code == 404:
                pass
            else:
                raise err

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
        if self.config.get('singlesocket'):
            cmd = "lscpu -p=socket|grep -v '#'"
            res = self.get_ssh_client().run_remote_command(cmd)
            sockets = set()
            for char in res:
                if char != '\n':
                    sockets.add(char)
            if len(sockets) != 1:
                raise LithopsValidationError(f'Not using single CPU socket as specified, using {len(sockets)} sockets instead')


RETRIABLE = ['list_vpcs',
             'create_vpc',
             'get_security_group',
             'create_security_group_rule',
             'list_public_gateways',
             'create_public_gateway',
             'list_subnets',
             'create_subnet',
             'set_subnet_public_gateway',
             'list_floating_ips',
             'create_floating_ip',
             'get_instance',
             'delete_instance',
             'list_instances',
             'list_instance_network_interface_floating_ips',
             'delete_floating_ip',
             'delete_subnet',
             'delete_public_gateway',
             'delete_vpc',
             'get_instance_initialization',
             'get_key',
             'create_instance',
             'add_instance_network_interface_floating_ip',
             'get_instance',
             'create_instance_action',
             'delete_instance']


def decorate_instance(instance, decorator):
    for name, func in inspect.getmembers(instance, inspect.ismethod):
        if name in RETRIABLE:
            setattr(instance, name, decorator(func))
    return instance


def vpc_retry_on_except(func):

    RETRIES = 3
    SLEEP_FACTOR = 1.5
    MAX_SLEEP = 30

    IGNORED_404_METHODS = ['delete_instance', 'delete_public_gateway', 'delete_vpc', 'create_instance_action']

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        sleep_time = 1

        def _sleep_or_raise(sleep_time, err):
            if i < RETRIES - 1:
                time.sleep(sleep_time)
                logger.warning((f'Got exception {err}, retrying for the {i} time, left retries {RETRIES - 1 -i}'))
                return min(sleep_time * SLEEP_FACTOR, MAX_SLEEP)
            else:
                raise err

        for i in range(RETRIES):
            try:
                return func(*args, **kwargs)
            except ApiException as err:
                if func.__name__ in IGNORED_404_METHODS and err.code == 404:
                    logger.debug((f'Got exception {err} when trying to invoke {func.__name__}, ignoring'))
                else:
                    sleep_time = _sleep_or_raise(sleep_time, err)
            except Exception as err:
                sleep_time = _sleep_or_raise(sleep_time, err)
    return wrapper
