#
# Copyright Cloudlab URV 2021
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
import boto3
import botocore
from botocore.exceptions import ClientError
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from lithops.version import __version__
from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import CLOUD_CONFIG_WORKER, CLOUD_CONFIG_WORKER_PK, StandaloneMode, get_host_setup_script
from lithops.standalone import LithopsValidationError


logger = logging.getLogger(__name__)

INSTANCE_STX_TIMEOUT = 180

DEFAULT_UBUNTU_IMAGE = 'ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*'
DEFAULT_UBUNTU_IMAGE_VERSION = DEFAULT_UBUNTU_IMAGE.replace('*', '202306*')
DEFAULT_UBUNTU_ACCOUNT_ID = '099720109477'

DEFAULT_LITHOPS_IMAGE_NAME = 'lithops-ubuntu-jammy-22.04-amd64-server'


def b64s(string):
    """
    Base-64 encode a string and return a string
    """
    return base64.b64encode(string.encode('utf-8')).decode('ascii')


class AWSEC2Backend:

    def __init__(self, ec2_config, mode):
        logger.debug("Creating AWS EC2 client")
        self.name = 'aws_ec2'
        self.config = ec2_config
        self.mode = mode
        self.region_name = self.config['region']

        suffix = 'vm' if self.mode == StandaloneMode.CONSUME.value else 'vpc'
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, f'{self.region_name}_{suffix}_data')

        self.vpc_data_type = 'provided' if 'vpc_id' in self.config else 'created'
        self.ssh_data_type = 'provided' if 'ssh_key_name' in self.config else 'created'

        self.ec2_data = {}
        self.vpc_name = None
        self.vpc_key = None

        self.instance_types = {}

        self.aws_session = boto3.Session(
            aws_access_key_id=ec2_config.get('access_key_id'),
            aws_secret_access_key=ec2_config.get('secret_access_key'),
            aws_session_token=ec2_config.get('session_token'),
            region_name=self.region_name
        )

        self.ec2_client = self.aws_session.client(
            'ec2', config=botocore.client.Config(
                user_agent_extra=self.config['user_agent']
            )
        )

        if 'user_id' not in self.config:
            sts_client = self.aws_session.client('sts')
            identity = sts_client.get_caller_identity()

        self.user_id = self.config.get('user_id') or identity["UserId"]
        self.user_key = self.user_id.split(":")[0][-4:].lower()

        self.master = None
        self.workers = []

        msg = COMPUTE_CLI_MSG.format('AWS EC2')
        logger.info(f"{msg} - Region: {self.region_name}")

    def is_initialized(self):
        """
        Checks if the backend is initialized
        """
        return os.path.isfile(self.cache_file)

    def _load_ec2_data(self):
        """
        Loads EC2 data from local cache
        """
        self.ec2_data = load_yaml_config(self.cache_file)

        if self.ec2_data:
            logger.debug(f'EC2 data loaded from {self.cache_file}')

        if 'vpc_id' in self.ec2_data:
            self.vpc_key = self.ec2_data['vpc_id'][-6:]
            self.vpc_name = self.ec2_data['vpc_name']

    def _dump_ec2_data(self):
        """
        Dumps EC2 data to local cache
        """
        dump_yaml_config(self.cache_file, self.ec2_data)

    def _delete_vpc_data(self):
        """
        Deletes the vpc data file
        """
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)

    def _create_vpc(self):
        """
        Creates a new VPC
        """
        if 'vpc_id' in self.config:
            return

        if 'vpc_id' in self.ec2_data:
            logger.debug(f'Using VPC {self.ec2_data["vpc_name"]}')
            vpcs_info = self.ec2_client.describe_vpcs(VpcIds=[self.ec2_data['vpc_id']])
            if len(vpcs_info) > 0:
                self.config['vpc_id'] = self.ec2_data['vpc_id']
                return

        self.vpc_name = self.config.get('vpc_name', f'lithops-vpc-{self.user_key}-{str(uuid.uuid4())[-6:]}')
        logger.debug(f'Setting VPC name to {self.vpc_name}')

        assert re.match("^[a-z0-9-:-]*$", self.vpc_name), \
            f'VPC name "{self.vpc_name}" not valid'

        filter = [{'Name': 'tag:Name', 'Values': [self.vpc_name]}]
        vpcs_info = self.ec2_client.describe_vpcs(Filters=filter)['Vpcs']
        if len(vpcs_info) > 0:
            self.config['vpc_id'] = vpcs_info[0]['VpcId']

        if 'vpc_id' not in self.config:
            logger.debug(f'Creating VPC {self.vpc_name}')
            response = self.ec2_client.create_vpc(CidrBlock='10.0.0.0/16')
            tags = [{"Key": "Name", "Value": self.vpc_name}]
            self.ec2_client.create_tags(Resources=[response['Vpc']['VpcId']], Tags=tags)

            self.config['vpc_id'] = response['Vpc']['VpcId']

    def _create_subnets(self):
        """
        Creates a public and a private subnets
        """
        if 'public_subnet_id' in self.config:
            return

        if 'public_subnet_id' in self.ec2_data:
            sg_info = self.ec2_client.describe_subnets(
                SubnetIds=[self.ec2_data['public_subnet_id']]
            )
            if len(sg_info) > 0:
                self.config['public_subnet_id'] = self.ec2_data['public_subnet_id']

        if 'public_subnet_id' not in self.config:
            logger.debug(f'Creating new public subnet in VPC {self.vpc_name}')
            response = self.ec2_client.create_subnet(
                CidrBlock='10.0.1.0/24', VpcId=self.config['vpc_id'],
            )
            public_subnet_id = response['Subnet']['SubnetId']
            self.config['public_subnet_id'] = public_subnet_id

        # if 'private_subnet_id' in self.ec2_data:
        #     sg_info = self.ec2_client.describe_subnets(
        #         SubnetIds=[self.ec2_data['private_subnet_id']]
        #     )
        #     if len(sg_info) > 0:
        #         self.config['private_subnet_id'] = self.ec2_data['private_subnet_id']
        #
        # if 'private_subnet_id' not in self.config:
        #     logger.debug(f'Creating new private subnet in VPC {self.vpc_name}')
        #     response = self.ec2_client.create_subnet(
        #         CidrBlock='10.0.2.0/24', VpcId=self.config['vpc_id']
        #     )
        #     private_subnet_id = response['Subnet']['SubnetId']
        #     self.config['private_subnet_id'] = private_subnet_id

    def _create_internet_gateway(self):
        """
        Creates a new internet gateway
        """
        if 'internet_gateway_id' in self.config:
            return

        if 'internet_gateway_id' in self.ec2_data:
            ig_info = self.ec2_client.describe_internet_gateways(
                InternetGatewayIds=[self.ec2_data['internet_gateway_id']]
            )
            if len(ig_info) > 0:
                self.config['internet_gateway_id'] = self.ec2_data['internet_gateway_id']
                return

        response = self.ec2_client.describe_internet_gateways()
        for ig in response['InternetGateways']:
            if ig['Attachments'][0]['VpcId'] == self.config['vpc_id']:
                self.config['internet_gateway_id'] = ig['InternetGatewayId']

        if 'internet_gateway_id' not in self.config:
            # Create and Attach the Internet Gateway
            logger.debug(f'Creating Internet Gateway in VPC {self.vpc_name}')
            response = self.ec2_client.create_internet_gateway()
            internet_gateway_id = response['InternetGateway']['InternetGatewayId']
            self.ec2_client.attach_internet_gateway(
                VpcId=self.config['vpc_id'], InternetGatewayId=internet_gateway_id
            )
            self.config['internet_gateway_id'] = internet_gateway_id

    def _create_nat_gateway(self):
        """
        Creates a new internet gateway
        """
        if 'nat_gateway_id' in self.config:
            return

        if 'nat_gateway_id' in self.ec2_data:
            ig_info = self.ec2_client.describe_nat_gateways(
                NatGatewayIds=[self.ec2_data['nat_gateway_id']]
            )
            if len(ig_info) > 0:
                self.config['nat_gateway_id'] = self.ec2_data['nat_gateway_id']
                return

        response = self.ec2_client.describe_nat_gateways()
        for ng in response['NatGateways']:
            if ng['SubnetId'] == self.config['public_subnet_id']:
                self.config['nat_gateway_id'] = ng['NatGatewayId']

        if 'nat_gateway_id' not in self.config:
            logger.debug(f'Creating NAT Gateway in VPC {self.vpc_name}')
            # Create an Elastic IP address for the NAT Gateway
            # Create the NAT gateway can take up to 2 minutes
            # TODO: Reuse Elastic IP adress if available
            eip_resp = self.ec2_client.allocate_address(Domain='vpc')
            allocation_id = eip_resp['AllocationId']

            # Create a NAT Gateway
            nat_gateway_resp = self.ec2_client.create_nat_gateway(
                SubnetId=self.config['public_subnet_id'],
                AllocationId=allocation_id
            )
            nat_gateway_id = nat_gateway_resp['NatGateway']['NatGatewayId']
            self.config['nat_gateway_id'] = nat_gateway_id

            self.ec2_client.get_waiter('nat_gateway_available').wait(
                NatGatewayIds=[nat_gateway_id],
                WaiterConfig={'Delay': 5, 'MaxAttempts': 40}
            )

    def _create_routing_tables(self):
        """
        Creates the routing tables
        """
        if 'public_rtb_id' in self.config:
            return

        if 'public_rtb_id' in self.ec2_data:
            sg_info = self.ec2_client.describe_route_tables(
                RouteTableIds=[self.ec2_data['public_rtb_id']]
            )
            if len(sg_info) > 0:
                self.config['public_rtb_id'] = self.ec2_data['public_rtb_id']

        if 'public_rtb_id' not in self.config:
            logger.debug(f'Creating public routing table in VPC {self.vpc_name}')
            # The default RT is the public RT
            response = self.ec2_client.describe_route_tables()
            for rt in response['RouteTables']:
                if rt['VpcId'] == self.config['vpc_id']:
                    publ_route_table_id = rt['RouteTableId']
            self.ec2_client.create_tags(
                Resources=[publ_route_table_id],
                Tags=[{'Key': 'Name', 'Value': f'{self.vpc_name}-publ'}]
            )
            self.ec2_client.associate_route_table(
                RouteTableId=publ_route_table_id,
                SubnetId=self.config['public_subnet_id']
            )
            self.ec2_client.create_route(
                RouteTableId=publ_route_table_id,
                DestinationCidrBlock='0.0.0.0/0',
                GatewayId=self.config['internet_gateway_id']
            )
            self.config['public_rtb_id'] = publ_route_table_id

        # if 'private_rtb_id' in self.ec2_data:
        #     sg_info = self.ec2_client.describe_route_tables(
        #         RouteTableIds=[self.ec2_data['private_rtb_id']]
        #     )
        #     if len(sg_info) > 0:
        #         self.config['private_rtb_id'] = self.ec2_data['private_rtb_id']
        #
        # if 'private_rtb_id' not in self.config:
        #     logger.debug(f'Creating private routing table in VPC {self.vpc_name}')
        #     # Create private RT
        #     priv_route_table_resp = self.ec2_client.create_route_table(
        #         VpcId=self.config['vpc_id']
        #     )
        #     priv_route_table_id = priv_route_table_resp['RouteTable']['RouteTableId']
        #     self.ec2_client.create_tags(
        #         Resources=[priv_route_table_id],
        #         Tags=[{'Key': 'Name', 'Value': f'{self.vpc_name}-priv'}]
        #     )
        #     self.ec2_client.associate_route_table(
        #         RouteTableId=priv_route_table_id,
        #         SubnetId=self.config['private_subnet_id']
        #     )
        #     self.ec2_client.create_route(
        #         RouteTableId=priv_route_table_id,
        #         DestinationCidrBlock='0.0.0.0/0',
        #         GatewayId=self.config['nat_gateway_id']
        #     )
        #     self.config['private_rtb_id'] = priv_route_table_id

    def _create_security_group(self):
        """
        Creates a new Security group
        """
        if 'security_group_id' in self.config:
            return

        if 'security_group_id' in self.ec2_data:
            sg_info = self.ec2_client.describe_security_groups(
                GroupIds=[self.ec2_data['security_group_id']]
            )
            if len(sg_info) > 0:
                self.config['security_group_id'] = self.ec2_data['security_group_id']
                return

        response = self.ec2_client.describe_security_groups()
        for sg in response['SecurityGroups']:
            if sg['VpcId'] == self.config['vpc_id'] and sg['GroupName'] == self.vpc_name:
                self.config['security_group_id'] = sg['GroupId']

        if 'security_group_id' not in self.config:
            logger.debug(f'Creating Security Group in VPC {self.vpc_name}')
            response = self.ec2_client.create_security_group(
                GroupName=self.vpc_name,
                Description=self.vpc_name,
                VpcId=self.config['vpc_id']
            )

            self.ec2_client.authorize_security_group_ingress(
                GroupId=response['GroupId'],
                IpPermissions=[
                    {'IpProtocol': 'tcp',
                        'FromPort': 8080,
                        'ToPort': 8080,
                        'IpRanges': [{'CidrIp': '10.0.0.0/16'}]},
                    {'IpProtocol': 'tcp',
                        'FromPort': 8081,
                        'ToPort': 8081,
                        'IpRanges': [{'CidrIp': '10.0.0.0/16'}]},
                    {'IpProtocol': 'tcp',
                        'FromPort': 6379,
                        'ToPort': 6379,
                        'IpRanges': [{'CidrIp': '10.0.0.0/16'}]},
                    {'IpProtocol': 'tcp',
                        'FromPort': 22,
                        'ToPort': 22,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )

            self.config['security_group_id'] = response['GroupId']

    def _create_ssh_key(self):
        """
        Creates a new ssh key pair
        """
        if 'ssh_key_name' in self.config:
            return

        if 'ssh_key_name' in self.ec2_data:
            key_info = self.ec2_client.describe_key_pairs(KeyNames=[self.ec2_data['ssh_key_name']])
            if len(key_info) > 0:
                self.config['ssh_key_name'] = self.ec2_data['ssh_key_name']
                self.config['ssh_key_filename'] = self.ec2_data['ssh_key_filename']
                return

        keyname = f'lithops-key-{str(uuid.uuid4())[-8:]}'
        filename = os.path.join("~", ".ssh", f"{keyname}.{self.name}.id_rsa")
        key_filename = os.path.expanduser(filename)

        if not os.path.isfile(key_filename):
            logger.debug("Generating new ssh key pair")
            os.system(f'ssh-keygen -b 2048 -t rsa -f {key_filename} -q -N ""')
            logger.debug(f"SHH key pair generated: {key_filename}")
            try:
                self.ec2_client.delete_key_pair(KeyName=keyname)
            except ClientError:
                pass
        else:
            key_pairs = self.ec2_client.describe_key_pairs(KeyNames=[keyname])['KeyPairs']
            if len(key_pairs) > 0:
                self.config['ssh_key_name'] = keyname

        if 'ssh_key_name' not in self.config:
            with open(f"{key_filename}.pub", "r") as file:
                ssh_key_data = file.read()
            self.ec2_client.import_key_pair(KeyName=keyname, PublicKeyMaterial=ssh_key_data)
            self.config['ssh_key_name'] = keyname

        self.config['ssh_key_filename'] = key_filename

    def _request_image_id(self):
        """
        Requests the default image ID if not provided
        """
        if 'target_ami' in self.config:
            return

        if 'target_ami' in self.ec2_data:
            self.config['target_ami'] = self.ec2_data['target_ami']

        if 'target_ami' not in self.config:
            response = self.ec2_client.describe_images(Filters=[
                {
                    'Name': 'name',
                    'Values': [DEFAULT_LITHOPS_IMAGE_NAME]
                }])

            for image in response['Images']:
                if image['Name'] == DEFAULT_LITHOPS_IMAGE_NAME:
                    logger.debug(f"Found default AMI: {DEFAULT_LITHOPS_IMAGE_NAME}")
                    self.config['target_ami'] = image['ImageId']
                    break

        if 'target_ami' not in self.config:
            response = self.ec2_client.describe_images(Filters=[
                {
                    'Name': 'name',
                    'Values': [DEFAULT_UBUNTU_IMAGE_VERSION]
                }], Owners=[DEFAULT_UBUNTU_ACCOUNT_ID])

            self.config['target_ami'] = response['Images'][0]['ImageId']

    def _create_master_instance(self):
        """
        Creates the master VM insatnce
        """
        name = self.config.get('master_name') or f'lithops-master-{self.vpc_key}'
        self.master = EC2Instance(name, self.config, self.ec2_client, public=True)
        self.master.instance_id = self.config['instance_id'] if self.mode == StandaloneMode.CONSUME.value else None
        self.master.instance_type = self.config['master_instance_type']
        self.master.delete_on_dismantle = False
        self.master.ssh_credentials.pop('password')
        self.master.get_instance_data()

    def _request_spot_price(self):
        """
        Requests the SPOT price
        """
        if self.config['request_spot_instances']:
            wit = self.config["worker_instance_type"]
            logger.debug(f'Requesting current spot price for worker VMs of type {wit}')
            response = self.ec2_client.describe_spot_price_history(
                EndTime=datetime.today(), InstanceTypes=[wit],
                ProductDescriptions=['Linux/UNIX (Amazon VPC)'],
                StartTime=datetime.today()
            )
            spot_prices = []
            for az in response['SpotPriceHistory']:
                spot_prices.append(float(az['SpotPrice']))
            self.config["spot_price"] = max(spot_prices)
            logger.debug(f'Current spot instance price for {wit} is ${self.config["spot_price"]}')

    def _get_all_instance_types(self):
        """
        Gets all instance types and their CPU COUNT
        """
        if 'instance_types' in self.ec2_data:
            self.instance_types = self.ec2_data['instance_types']
            return

        instances = {}
        next_token = None

        while True:
            if next_token:
                response = self.ec2_client.describe_instance_types(NextToken=next_token)
            else:
                response = self.ec2_client.describe_instance_types()

            for instance_type in response['InstanceTypes']:
                instance_name = instance_type['InstanceType']
                cpu_count = instance_type['VCpuInfo']['DefaultVCpus']
                instances[instance_name] = cpu_count

            next_token = response.get('NextToken')

            if not next_token:
                break

        self.instance_types = instances

    def init(self):
        """
        Initialize the backend by defining the Master VM
        """
        logger.debug(f'Initializing AWS EC2 backend ({self.mode} mode)')

        self._load_ec2_data()

        if self.mode == StandaloneMode.CONSUME.value:
            ins_id = self.config['instance_id']
            if not self.ec2_data or ins_id != self.ec2_data.get('instance_id'):
                instances = self.ec2_client.describe_instances(InstanceIds=[ins_id])
                instance_data = instances['Reservations'][0]['Instances'][0]
                master_name = 'lithops-consume'
                for tag in instance_data['Tags']:
                    if tag['Key'] == 'Name':
                        master_name = tag['Value']
                self.ec2_data = {
                    'mode': self.mode,
                    'vpc_data_type': 'provided',
                    'ssh_data_type': 'provided',
                    'master_name': master_name,
                    'master_id': self.config['instance_id'],
                    'instance_type': instance_data['InstanceType']
                }

            # Create the master VM instance
            self.config['master_name'] = self.ec2_data['master_name']
            self.config['master_instance_type'] = self.ec2_data['instance_type']
            self._create_master_instance()

        elif self.mode in [StandaloneMode.CREATE.value, StandaloneMode.REUSE.value]:

            # Create the VPC if not exists
            self._create_vpc()

            # Set the suffix used for the VPC resources
            self.vpc_key = self.config['vpc_id'][-6:]

            # Create the Subnet if not exists
            self._create_subnets()
            # Create the internet gateway if not exists
            self. _create_internet_gateway()
            # Create the NAT gateway
            # self._create_nat_gateway()
            # Create routing tables
            self._create_routing_tables()
            # Create the security group if not exists
            self._create_security_group()
            # Create the ssh key pair if not exists
            self._create_ssh_key()
            # Requests the Ubuntu image ID
            self._request_image_id()
            # Request SPOT price
            self._request_spot_price()
            # Request instance types
            self._get_all_instance_types()

            # Create the master VM instance
            self._create_master_instance()

            self.ec2_data = {
                'mode': self.mode,
                'vpc_data_type': self.vpc_data_type,
                'ssh_data_type': self.ssh_data_type,
                'master_name': self.master.name,
                'master_id': self.vpc_key,
                'vpc_name': self.vpc_name,
                'vpc_id': self.config['vpc_id'],
                'instance_role': self.config['instance_role'],
                'target_ami': self.config['target_ami'],
                'ssh_key_name': self.config['ssh_key_name'],
                'ssh_key_filename': self.config['ssh_key_filename'],
                'public_subnet_id': self.config['public_subnet_id'],
                # 'private_subnet_id': self.config['private_subnet_id'],
                'security_group_id': self.config['security_group_id'],
                'internet_gateway_id': self.config['internet_gateway_id'],
                # 'nat_gateway_id': self.config['nat_gateway_id'],
                # 'private_rtb_id': self.config['private_rtb_id'],
                'public_rtb_id': self.config['public_rtb_id'],
                'instance_types': self.instance_types
            }

        self._dump_ec2_data()

    def build_image(self, image_name, script_file, overwrite, include, extra_args=[]):
        """
        Builds a new VM Image
        """
        image_name = image_name or DEFAULT_LITHOPS_IMAGE_NAME

        images = self.ec2_client.describe_images(Filters=[
            {
                'Name': 'name',
                'Values': [image_name]
            }])['Images']

        if len(images) > 0:
            image_id = images[0]['ImageId']
            if overwrite:
                self.delete_image(image_name)
            else:
                raise Exception(f"The image with name '{image_name}' already exists with ID: '{image_id}'."
                                " Use '--overwrite' or '-o' if you want ot overwrite it")

        is_initialized = self.is_initialized()
        self.init()

        try:
            del self.config['target_ami']
        except Exception:
            pass
        try:
            del self.ec2_data['target_ami']
        except Exception:
            pass

        self._request_image_id()

        build_vm = EC2Instance('building-image-' + image_name, self.config, self.ec2_client, public=True)
        build_vm.delete_on_dismantle = False
        build_vm.create()
        build_vm.wait_ready()

        logger.debug(f"Uploading installation script to {build_vm}")
        remote_script = "/tmp/install_lithops.sh"
        script = get_host_setup_script()
        build_vm.get_ssh_client().upload_data_to_file(script, remote_script)
        logger.debug("Executing Lithops installation script. Be patient, this process can take up to 3 minutes")
        build_vm.get_ssh_client().run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};")
        logger.debug("Lithops installation script finsihed")

        for src_dst_file in include:
            src_file, dst_file = src_dst_file.split(':')
            if os.path.isfile(src_file):
                logger.debug(f"Uploading local file '{src_file}' to VM image in '{dst_file}'")
                build_vm.get_ssh_client().upload_local_file(src_file, dst_file)

        if script_file:
            script = os.path.expanduser(script_file)
            logger.debug(f"Uploading user script '{script_file}' to {build_vm}")
            remote_script = "/tmp/install_user_lithops.sh"
            build_vm.get_ssh_client().upload_local_file(script, remote_script)
            logger.debug(f"Executing user script '{script_file}'")
            build_vm.get_ssh_client().run_remote_command(f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};")
            logger.debug(f"User script '{script_file}' finsihed")

        build_vm_id = build_vm.get_instance_id()

        build_vm.stop()
        build_vm.wait_stopped()

        self.ec2_client.create_image(
            InstanceId=build_vm_id,
            Name=image_name,
            Description='Lithops Image'
        )

        logger.debug("Starting VM image creation")
        logger.debug("Be patient, VM imaging can take up to 5 minutes")

        while True:
            images = self.ec2_client.describe_images(Filters=[{'Name': 'name', 'Values': [image_name]}])['Images']
            if len(images) > 0:
                logger.debug(f"VM Image is being created. Current status: {images[0]['State']}")
                if images[0]['State'] == 'available':
                    break
            time.sleep(20)

        if not is_initialized:
            while not self.clean(all=True):
                time.sleep(5)
        else:
            build_vm.delete()

        logger.info(f"VM Image created. Image ID: {images[0]['ImageId']}")

    def delete_image(self, image_name):
        """
        Deletes a VM Image
        """
        def list_images():
            return self.ec2_client.describe_images(Filters=[
                {
                    'Name': 'name',
                    'Values': [image_name]
                }])['Images']

        images = list_images()

        if len(images) > 0:
            image_id = images[0]['ImageId']
            logger.debug(f"Deleting existing VM Image '{image_name}'")
            self.ec2_client.deregister_image(ImageId=image_id)
            while len(list_images()) > 0:
                time.sleep(2)
            logger.debug(f"VM Image '{image_name}' successfully deleted")

    def list_images(self):
        """
        List VM Images
        """
        images_def = self.ec2_client.describe_images(Filters=[
            {
                'Name': 'name',
                'Values': [DEFAULT_UBUNTU_IMAGE]
            }], Owners=[DEFAULT_UBUNTU_ACCOUNT_ID])['Images']
        images_user = self.ec2_client.describe_images(Filters=[
            {
                'Name': 'name',
                'Values': ['*lithops*']
            }])['Images']
        images_def.extend(images_user)

        result = set()

        for image in images_def:
            created_at = datetime.strptime(image['CreationDate'], "%Y-%m-%dT%H:%M:%S.%fZ")
            created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
            result.add((image['Name'], image['ImageId'], created_at))

        return sorted(result, key=lambda x: x[2], reverse=True)

    def _delete_vm_instances(self, all=False):
        """
        Deletes all worker VM instances
        """
        msg = (f'Deleting all Lithops worker VMs from {self.vpc_name}'
               if self.vpc_name else 'Deleting all Lithops worker VMs')
        logger.info(msg)

        vms_prefixes = ('lithops-worker', 'lithops-master', 'building-image') if all else ('lithops-worker',)

        ins_to_delete = []
        response = self.ec2_client.describe_instances()
        for res in response['Reservations']:
            for ins in res['Instances']:
                if ins['State']['Name'] != 'terminated' and 'Tags' in ins \
                   and 'VpcId' in ins and self.ec2_data['vpc_id'] == ins['VpcId']:
                    for tag in ins['Tags']:
                        if tag['Key'] == 'Name' and tag['Value'].startswith(vms_prefixes):
                            ins_to_delete.append(ins['InstanceId'])
                            logger.debug(f"Going to delete VM instance {tag['Value']} ({ins['InstanceId']})")

        if ins_to_delete:
            self.ec2_client.terminate_instances(InstanceIds=ins_to_delete)

        master_pk = os.path.join(self.cache_dir, f"{self.ec2_data['master_name']}-id_rsa.pub")
        if all and os.path.isfile(master_pk):
            os.remove(master_pk)

        if self.ec2_data['vpc_data_type'] == 'provided':
            return

        while all and ins_to_delete:
            logger.debug('Waiting for VM instances to be terminated')
            status = set()
            response = self.ec2_client.describe_instances()
            for res in response['Reservations']:
                for ins in res['Instances']:
                    if ins['InstanceId'] in ins_to_delete:
                        status.add(ins['State']['Name'])
            if len(status) == 1 and status.pop() == 'terminated':
                break
            else:
                time.sleep(8)

    def _delete_vpc(self):
        """
        Deletes all the VPC resources
        """
        if self.ec2_data['vpc_data_type'] == 'provided':
            return

        msg = (f'Deleting all Lithops VPC resources from {self.vpc_name}'
               if self.vpc_name else 'Deleting all Lithops VPC resources')
        logger.info(msg)

        total_correct = 0

        # Security Group
        try:
            logger.debug(f"Deleting security group {self.ec2_data['security_group_id']}")
            self.ec2_client.delete_security_group(
                GroupId=self.ec2_data['security_group_id']
            )
            total_correct += 1
        except ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
               'does not exist' in e.response['Error']['Message']:
                total_correct += 1
            logger.debug(e.response['Error']['Message'])

        # NAT Gateway
        # try:
        #     logger.debug(f"Deleting nat gateway {self.ec2_data['nat_gateway_id']}")
        #     self.ec2_client.delete_nat_gateway(
        #         NatGatewayId=self.ec2_data['nat_gateway_id']
        #     )
        #     self.ec2_client.get_waiter('nat_gateway_deleted').wait(
        #         NatGatewayIds=[self.ec2_data['nat_gateway_id']],
        #         WaiterConfig={'Delay': 5, 'MaxAttempts': 40}
        #     )
        #     total_correct += 1
        # except ClientError as e:
        #     if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
        #        'does not exist' in e.response['Error']['Message']:
        #         total_correct += 1
        #     logger.debug(e.response['Error']['Message'])

        # Subnets
        try:
            logger.debug(f"Deleting public {self.ec2_data['public_subnet_id']}")
            self.ec2_client.delete_subnet(SubnetId=self.ec2_data['public_subnet_id'])
            total_correct += 1
        except ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
               'does not exist' in e.response['Error']['Message']:
                total_correct += 1
            logger.debug(e.response['Error']['Message'])
        # try:
        #     logger.debug(f"Deleting private {self.ec2_data['private_subnet_id']}")
        #     self.ec2_client.delete_subnet(SubnetId=self.ec2_data['private_subnet_id'])
        #     total_correct += 1
        # except ClientError as e:
        #     if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
        #        'does not exist' in e.response['Error']['Message']:
        #         total_correct += 1
        #     logger.debug(e.response['Error']['Message'])

        # Internet gateway
        try:
            logger.debug(f"Detaching internet gateway {self.ec2_data['internet_gateway_id']}")
            self.ec2_client.detach_internet_gateway(
                InternetGatewayId=self.ec2_data['internet_gateway_id'],
                VpcId=self.ec2_data['vpc_id'])
            total_correct += 1
        except ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
               'does not exist' in e.response['Error']['Message']:
                total_correct += 1
            logger.debug(e.response['Error']['Message'])
        try:
            logger.debug(f"Deleting internet gateway {self.ec2_data['internet_gateway_id']}")
            self.ec2_client.delete_internet_gateway(
                InternetGatewayId=self.ec2_data['internet_gateway_id']
            )
            total_correct += 1
        except ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
               'does not exist' in e.response['Error']['Message']:
                total_correct += 1
            logger.debug(e.response['Error']['Message'])

        # VPC
        try:
            logger.debug(f"Deleting VPC {self.ec2_data['vpc_id']}")
            self.ec2_client.delete_vpc(VpcId=self.ec2_data['vpc_id'])
            total_correct += 1
        except ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 400 and \
               'does not exist' in e.response['Error']['Message']:
                total_correct += 1
            logger.debug(e.response['Error']['Message'])

        if total_correct < 5:
            logger.error("Couldn't delete all the VPC resources, try againg in a few seconds")

        return total_correct == 5

    def _delete_ssh_key(self):
        """
        Deletes the ssh key
        """
        if self.ec2_data['ssh_data_type'] == 'provided':
            return

        key_filename = self.ec2_data['ssh_key_filename']
        if "lithops-key-" in key_filename:
            if os.path.isfile(key_filename):
                os.remove(key_filename)
            if os.path.isfile(f"{key_filename}.pub"):
                os.remove(f"{key_filename}.pub")

        if 'ssh_key_name' in self.ec2_data:
            logger.debug(f"Deleting SSH key {self.ec2_data['ssh_key_name']}")
            try:
                self.ec2_client.delete_key_pair(KeyName=self.ec2_data['ssh_key_name'])
            except ClientError as e:
                logger.debug(e)

    def clean(self, all=False):
        """
        Clean all the VPC resources
        """
        logger.info('Cleaning AWS EC2 resources')

        if not self.ec2_data:
            return True

        if self.mode == StandaloneMode.CONSUME.value:
            self._delete_vpc_data()
            return True
        else:
            self._delete_vm_instances(all=all)
            if all:
                if self._delete_vpc():
                    self._delete_ssh_key()
                    self._delete_vpc_data()
                    return True
                else:
                    return False

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
        instance = EC2Instance(name, self.config, self.ec2_client)

        for key in kwargs:
            if hasattr(instance, key) and kwargs[key] is not None:
                setattr(instance, key, kwargs[key])

        return instance

    def get_worker_instance_type(self):
        """
        Return the worker instance type
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
        worker = EC2Instance(name, self.config, self.ec2_client, public=False)

        user = worker.ssh_credentials['username']

        pub_key = f'{self.cache_dir}/{self.master.name}-id_rsa.pub'
        if os.path.isfile(pub_key):
            with open(pub_key, 'r') as pk:
                pk_data = pk.read().strip()
            user_data = CLOUD_CONFIG_WORKER_PK.format(user, pk_data)
            worker.ssh_credentials['key_filename'] = '~/.ssh/lithops_id_rsa'
            worker.ssh_credentials.pop('password')
        else:
            logger.error(f'Unable to locate {pub_key}')
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
        runtime_key = os.path.join(self.name, version, self.ec2_data['master_id'], name)
        return runtime_key


class EC2Instance:

    def __init__(self, name, ec2_config, ec2_client=None, public=False):
        """
        Initialize a EC2Instance instance
        VMs can have master role, this means they will have a public IP address
        """
        self.name = name.lower()
        self.config = ec2_config

        self.delete_on_dismantle = self.config['delete_on_dismantle']
        self.instance_type = self.config['worker_instance_type']
        self.region_name = self.config['region']
        self.spot_instance = self.config['request_spot_instances']

        self.ec2_client = ec2_client or self._create_ec2_client()
        self.public = public

        self.ssh_client = None
        self.instance_id = None
        self.instance_data = None
        self.private_ip = None
        self.public_ip = '0.0.0.0'
        self.fast_io = self.config.get('fast_io', False)
        self.home_dir = '/home/ubuntu'

        self.runtime_name = None

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', '~/.ssh/id_rsa')
        }

    def __str__(self):
        ip = self.public_ip if self.public else self.private_ip

        if ip is None or ip == '0.0.0.0':
            return f'VM instance {self.name}'
        else:
            return f'VM instance {self.name} ({ip})'

    def _create_ec2_client(self):
        """
        Creates an EC2 boto3 instance
        """
        client_config = botocore.client.Config(
            user_agent_extra=self.config['user_agent']
        )

        ec2_client = boto3.client(
            'ec2', aws_access_key_id=self.config['access_key_id'],
            aws_secret_access_key=self.config['secret_access_key'],
            aws_session_token=self.config.get('session_token'),
            config=client_config,
            region_name=self.region_name
        )

        return ec2_client

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

    def wait_ready(self, timeout=INSTANCE_STX_TIMEOUT):
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

    def is_stopped(self):
        """
        Checks if the VM instance is stoped
        """
        state = self.get_instance_data()['State']
        if state['Name'] == 'stopped':
            return True
        return False

    def wait_stopped(self, timeout=INSTANCE_STX_TIMEOUT):
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

    def _create_instance(self, user_data=None):
        """
        Creates a new VM instance
        """
        if self.fast_io:
            BlockDeviceMappings = [
                {
                    'DeviceName': '/dev/xvda',
                    'Ebs': {
                        'VolumeSize': 100,
                        'DeleteOnTermination': True,
                        'VolumeType': 'gp2',
                        # 'Iops' : 10000,
                    },
                },
            ]
        else:
            BlockDeviceMappings = None

        LaunchSpecification = {
            "ImageId": self.config['target_ami'],
            "InstanceType": self.instance_type,
            "EbsOptimized": False,
            "IamInstanceProfile": {'Name': self.config['instance_role']},
            "Monitoring": {'Enabled': False},
            'KeyName': self.config['ssh_key_name']
        }

        LaunchSpecification['NetworkInterfaces'] = [{
            'AssociatePublicIpAddress': True,
            'DeviceIndex': 0,
            'SubnetId': self.config['public_subnet_id'],
            'Groups': [self.config['security_group_id']]
        }]

        if BlockDeviceMappings is not None:
            LaunchSpecification['BlockDeviceMappings'] = BlockDeviceMappings

        if self.spot_instance and not self.public:

            logger.debug(f"Creating new VM instance {self.name} (Spot)")

            if user_data:
                # Allow master VM to access workers trough ssh key or password
                LaunchSpecification['UserData'] = b64s(user_data)

            spot_request = self.ec2_client.request_spot_instances(
                SpotPrice=str(self.config['spot_price']),
                InstanceCount=1,
                LaunchSpecification=LaunchSpecification)['SpotInstanceRequests'][0]

            request_id = spot_request['SpotInstanceRequestId']
            failures = ['price-too-low', 'capacity-not-available']

            while spot_request['State'] == 'open':
                time.sleep(5)
                spot_request = self.ec2_client.describe_spot_instance_requests(
                    SpotInstanceRequestIds=[request_id])['SpotInstanceRequests'][0]

                if spot_request['State'] == 'failed' or spot_request['Status']['Code'] in failures:
                    msg = "The spot request failed for the following reason: " + spot_request['Status']['Message']
                    logger.debug(msg)
                    self.ec2_client.cancel_spot_instance_requests(SpotInstanceRequestIds=[request_id])
                    raise Exception(msg)
                else:
                    logger.debug(spot_request['Status']['Message'])

            self.ec2_client.create_tags(
                Resources=[spot_request['InstanceId']],
                Tags=[{'Key': 'Name', 'Value': self.name}]
            )

            filters = [{'Name': 'instance-id', 'Values': [spot_request['InstanceId']]}]
            resp = self.ec2_client.describe_instances(Filters=filters)['Reservations'][0]

        else:
            logger.debug(f"Creating new VM instance {self.name}")

            LaunchSpecification['MinCount'] = 1
            LaunchSpecification['MaxCount'] = 1
            LaunchSpecification["TagSpecifications"] = [{"ResourceType": "instance", "Tags": [{'Key': 'Name', 'Value': self.name}]}]
            LaunchSpecification["InstanceInitiatedShutdownBehavior"] = 'terminate' if self.delete_on_dismantle else 'stop'

            if user_data:
                LaunchSpecification['UserData'] = user_data

            resp = self.ec2_client.run_instances(**LaunchSpecification)

        logger.debug(f"VM instance {self.name} created successfully ")

        self.instance_data = resp['Instances'][0]
        self.instance_id = self.instance_data['InstanceId']

        return self.instance_data

    def get_instance_data(self):
        """
        Returns the instance information
        """
        if self.instance_id:
            res = self.ec2_client.describe_instances(InstanceIds=[self.instance_id])
            reserv = res['Reservations']
        else:
            filters = [{'Name': 'tag:Name', 'Values': [self.name]}]
            res = self.ec2_client.describe_instances(Filters=filters)
            reserv = res['Reservations']

        instance_data = reserv[0]['Instances'][0] if len(reserv) > 0 else None

        if instance_data and instance_data['State']['Name'] != 'terminated':
            self.instance_data = instance_data
            self.instance_id = instance_data['InstanceId']
            self.private_ip = self.instance_data.get('PrivateIpAddress')
            self.public_ip = self.instance_data.get('PublicIpAddress')

        return self.instance_data

    def get_instance_id(self):
        """
        Returns the instance ID
        """
        if not self.instance_id and self.instance_data:
            self.instance_id = self.instance_data.get('InstanceId')

        if not self.instance_id:
            instance_data = self.get_instance_data()
            if instance_data:
                self.instance_id = instance_data['InstanceId']
            else:
                logger.debug(f'VM instance {self.name} does not exists')

        return self.instance_id

    def get_private_ip(self):
        """
        Requests the private IP address
        """
        if not self.private_ip and self.instance_data:
            self.private_ip = self.instance_data.get('PrivateIpAddress')

        while not self.private_ip:
            instance_data = self.get_instance_data()
            if instance_data and 'PrivateIpAddress' in instance_data:
                self.private_ip = instance_data['PrivateIpAddress']
            else:
                time.sleep(1)

        return self.private_ip

    def get_public_ip(self):
        """
        Requests the public IP address
        """
        if not self.public:
            return None

        if not self.public_ip and self.instance_data:
            self.public_ip = self.instance_data.get('PublicIpAddress')

        while not self.public_ip or self.public_ip == '0.0.0.0':
            instance_data = self.get_instance_data()
            if instance_data and 'PublicIpAddress' in instance_data:
                self.public_ip = instance_data['PublicIpAddress']
            else:
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
        logger.info(f"Starting VM instance {self.name} ({self.instance_id})")

        try:
            self.ec2_client.start_instances(InstanceIds=[self.instance_id])
            self.public_ip = self.get_public_ip()
        except botocore.exceptions.ClientError as err:
            if err.response['Error']['Code'] == 'IncorrectInstanceState':
                time.sleep(20)
                return self.start()
            raise err

        logger.debug(f"VM instance {self.name} started successfully")

    def _delete_instance(self):
        """
        Deletes the VM instance and the associated volume
        """
        logger.debug(f"Deleting VM instance {self.name} ({self.instance_id})")

        self.ec2_client.terminate_instances(InstanceIds=[self.instance_id])

        self.instance_data = None
        self.instance_id = None
        self.private_ip = None
        self.public_ip = '0.0.0.0'
        self.del_ssh_client()

    def _stop_instance(self):
        """
        Stops the VM instance
        """
        logger.debug(f"Stopping VM instance {self.name} ({self.instance_id})")
        self.ec2_client.stop_instances(InstanceIds=[self.instance_id])

        self.instance_data = None
        self.private_ip = None
        self.public_ip = '0.0.0.0'
        self.del_ssh_client()

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
