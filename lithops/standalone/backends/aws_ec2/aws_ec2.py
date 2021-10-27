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
import time
import logging
import boto3
import botocore
from concurrent.futures import ThreadPoolExecutor

from lithops.util.ssh_client import SSHClient
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import CLOUD_CONFIG_WORKER


logger = logging.getLogger(__name__)

# https://github.com/nchammas/flintrock/blob/master/flintrock/ec2.py
class AWSEC2Backend:

    def __init__(self, ec2_config, mode):
        logger.debug("Creating AWS EC2 client")
        self.name = 'aws_ec2'
        self.config = ec2_config
        self.mode = mode
        self.region = self.config['region_name']

        client_config = botocore.client.Config(
            user_agent_extra=self.config['user_agent']
        )

        self.ec2_client = boto3.client(
            'ec2', aws_access_key_id=ec2_config['access_key_id'],
            aws_secret_access_key=ec2_config['secret_access_key'],
            config=client_config,
            region_name=self.region
        )

        self.master = None
        self.workers = []

        msg = COMPUTE_CLI_MSG.format('AWS EC2')
        logger.info("{} - Region: {}".format(msg, self.region))

    def init(self):
        """
        Initialize the backend by defining the Master VM
        """
        ec2_data_filename = os.path.join(CACHE_DIR, self.name, 'data')
        self.ec2_data = load_yaml_config(ec2_data_filename)

        cahced_mode = self.ec2_data.get('mode')
        cahced_instance_id = self.ec2_data.get('instance_id')

        logger.debug(f'Initializing AWS EC2 backend ({self.mode} mode)')

        if self.mode == 'consume':
            ins_id = self.config['instance_id']

            if self.mode != cahced_mode or ins_id != cahced_instance_id:
                instances = self.ec2_client.describe_instances(InstanceIds=[ins_id])
                instance_data = instances['Reservations'][0]['Instances'][0]
                name = 'lithops-consume'
                for tag in instance_data['Tags']:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                private_ip = instance_data['NetworkInterfaces'][0]['PrivateIpAddress']
                self.ec2_data = {'mode': self.mode,
                                 'instance_id': ins_id,
                                 'instance_name': name,
                                 'private_ip': private_ip}
                dump_yaml_config(ec2_data_filename, self.ec2_data)

            self.master = EC2Instance(self.ec2_data['instance_name'], self.config, self.ec2_client, public=True)
            self.master.instance_id = ins_id
            self.master.ip_address = self.ec2_data['private_ip']
            self.master.delete_on_dismantle = False

        elif self.mode in ['create', 'reuse']:
            if self.mode != cahced_mode:
                # invalidate cached data
                self.vpc_data = {}

            self.vpc_key = self.config['vpc_id'][-4:]

            # create the master VM insatnce
            name = 'lithops-master-{}'.format(self.vpc_key)
            self.master = EC2Instance(name, self.config, self.ec2_client, public=True)
            self.master.instance_type = self.config['master_instance_type']
            self.master.delete_on_dismantle = False

            self.ec2_data = {
                'mode': self.mode,
                'instance_id': '0af1',
                'instance_name': self.master.name,
                'vpc_id': self.config['vpc_id']
            }

            dump_yaml_config(ec2_data_filename, self.ec2_data)

    def _delete_vm_instances(self):
        """
        Deletes all VM instances in the VPC
        """
        msg = ('Deleting all Lithops worker VMs in {}'.format(self.vpc_name)
               if self.vpc_name else 'Deleting all Lithops worker VMs')
        logger.info(msg)

        def delete_instance(instance_info):
            ins_name, ins_id = instance_info
            logger.info('Deleting instance {}'.format(ins_name))
            self.ibm_vpc_client.delete_instance(ins_id)

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

    def clean(self):
        """
        Clean all the backend resources
        The gateway public IP and the floating IP are never deleted
        """
        logger.debug('Cleaning AWS EC2 resources')
        self._delete_vm_instances()

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

        if include_master and self.mode in ['consume', 'reuse']:
            # in consume mode master VM is a worker
            self.master.stop()

    def get_vm(self, name):
        """
        Returns a VM class instance.
        Does not creates nor starts a VM instance
        """
        return EC2Instance(name, self.config, self.ec2_client)

    def create_worker(self, name):
        """
        Creates a new worker VM instance
        """
        vm = EC2Instance(name, self.config, self.ec2_client)
        vm.create()
        vm.ssh_credentials.pop('key_filename', None)
        self.workers.append(vm)

    def get_runtime_key(self, runtime_name):
        name = runtime_name.replace('/', '-').replace(':', '-')
        runtime_key = '/'.join([self.name, self.ec2_data['instance_id'], name])
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
        self.region = self.config['region_name']

        self.ec2_client = ec2_client or self._create_ec2_client()
        self.public = public

        self.ssh_client = None
        self.instance_id = None
        self.instance_data = None
        self.ip_address = None
        self.public_ip = '0.0.0.0'
        self.fast_io = self.config.get('fast_io', False)

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', None)
        }

    def __str__(self):
        return 'VM instance {} ({})'.format(self.name, self.public_ip or self.ip_address)

    def _create_ec2_client(self):
        """
        Creates an EC2 boto3 instance
        """
        client_config = botocore.client.Config(
            user_agent_extra=self.config['user_agent']
        )

        ec2_client = boto3.client(
            'ec2', aws_access_key_id=self.ec2_config['access_key_id'],
            aws_secret_access_key=self.ec2_config['secret_access_key'],
            config=client_config,
            region_name=self.region
        )

        return ec2_client

    def get_ssh_client(self):
        """
        Creates an ssh client against the VM only if the Instance is the master
        """
        if self.public:
            if not self.ssh_client or self.ssh_client.ip_address != self.public_ip:
                self.ssh_client = SSHClient(self.public_ip, self.ssh_credentials)
        else:
            if not self.ssh_client or self.ssh_client.ip_address != self.ip_address:
                self.ssh_client = SSHClient(self.ip_address, self.ssh_credentials)

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
            "MinCount": 1,
            "MaxCount": 1,
            "ImageId": self.config['target_ami'],
            "InstanceType": self.instance_type,
            "SecurityGroupIds": [self.config['security_group_id']],
            "EbsOptimized": False,
            "IamInstanceProfile": {'Name': self.config['iam_role']},
            "Monitoring": {'Enabled': False},
            "TagSpecifications": [{"ResourceType": "instance", "Tags": [{'Key': 'Name', 'Value': self.name}]}],
            "InstanceInitiatedShutdownBehavior": 'terminate' if self.delete_on_dismantle else 'stop'}

        if BlockDeviceMappings is not None:
            LaunchSpecification['BlockDeviceMappings'] = BlockDeviceMappings
        if 'key_name' in self.config:
            LaunchSpecification['KeyName'] = self.config['key_name']

        if not self.public:
            # Allow master VM to access workers trough ssh passwrod
            user = self.config['ssh_username']
            token = self.config['ssh_password']
            LaunchSpecification['UserData'] = CLOUD_CONFIG_WORKER.format(user, token)

        instance = self.ec2_client.run_instances(**LaunchSpecification)

        logger.debug("VM instance {} created successfully ".format(self.name))

        return instance['Instances'][0]

    def get_instance_data(self):
        """
        Returns the instance information
        """
        if self.instance_id:
            instances = self.ec2_client.describe_instances(InstanceIds=[self.instance_id])
            instances = instances['Reservations'][0]['Instances']
            if len(instances) > 0:
                self.instance_data = instances[0]
                return self.instance_data
        else:
            response = self.ec2_client.describe_instances()
            for r in response['Reservations']:
                for ins in r['Instances']:
                    if ins['State']['Name'] != 'terminated' and 'Tags' in ins:
                        for tag in ins['Tags']:
                            if tag['Key'] == 'Name' and self.name == tag['Value']:
                                self.instance_data = ins
                                return self.instance_data
        return None

    def get_instance_id(self):
        """
        Returns the instance ID
        """
        if self.instance_id:
            return self.instance_id

        instance_data = self.get_instance_data()
        if instance_data:
            self.instance_id = instance_data['InstanceId']
            return self.instance_id
        logger.debug('VM instance {} does not exists'.format(self.name))
        return None

    def _get_private_ip(self):
        """
        Requests the the primary network IP address
        """
        private_ip = None
        if self.instance_id:
            while not private_ip:
                instance_data = self.get_instance_data()
                if instance_data:
                    private_ip = instance_data['NetworkInterfaces'][0]['PrivateIpAddress']
        return private_ip

    def create(self, check_if_exists=False):
        """
        Creates a new VM instance
        """
        vsi_exists = True if self.instance_id else False

        if check_if_exists and not vsi_exists:
            logger.debug('Checking if VM instance {} already exists'.format(self.name))
            instances_data = self.get_instance_data()
            if instances_data:
                logger.debug('VM instance {} already exists'.format(self.name))
                vsi_exists = True
                self.instance_id = instances_data['InstanceId']

        if not vsi_exists:
            instances_data = self._create_instance()
            self.instance_id = instances_data['InstanceId']
            self.ip_address = instances_data['PrivateIpAddress']

        self.start()

        return self.instance_id

    def start(self):
        logger.debug("Starting VM instance {}".format(self.name))

        self.ec2_client.start_instances(InstanceIds=[self.instance_id])
        public_ip = ''

        while self.public and not public_ip:
            instances = self.ec2_client.describe_instances(InstanceIds=[self.instance_id])
            instance_data = instances['Reservations'][0]['Instances'][0]
            if 'PublicIpAddress' in instance_data:
                public_ip = instance_data['PublicIpAddress']
                self.public_ip = public_ip
            else:
                time.sleep(1)

        logger.debug("VM instance {} started successfully".format(self.name))

    def _delete_instance(self):
        """
        Deletes the VM instacne and the associated volume
        """
        logger.debug("Deleting VM instance {}".format(self.name))

        self.ec2_client.terminate_instances(InstanceIds=[self.instance_id])

        self.instance_id = None
        self.ip_address = None
        self.public_ip = None
        self.del_ssh_client()

    def _stop_instance(self):
        """
        Stops the VM instacne and
        """
        logger.debug("Stopping VM instance {}".format(self.name))
        self.ec2_client.stop_instances(InstanceIds=[self.instance_id])

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
