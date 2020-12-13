import os
import logging
import requests
import time
from lithops.constants import COMPUTE_CLI_MSG
from lithops.util.ibm_token_manager import IBMTokenManager

from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException
import namegenerator

logger = logging.getLogger(__name__)


class IBMVPCInstanceClient:

    def __init__(self, ibm_vpc_config):
        logger.debug("Creating IBM VPC client")
        
        self.name = 'ibm_vpc'
        self.config = ibm_vpc_config

        self.endpoint = self.config['endpoint']
        self.region = self.endpoint.split('//')[1].split('.')[0]
        self.instance_id = self.config['instance_id']
        self.ip_address = self.config.get('ip_address', None)

        self.instance_data = None

        self.ssh_credentials = {'username': self.config.get('ssh_user', 'root'),
                                'password': self.config.get('ssh_password', None),
                                'key_filename': self.config.get('ssh_key_filename', None)}

        self.session = requests.session()

        iam_api_key = self.config.get('iam_api_key')

        authenticator = IAMAuthenticator(iam_api_key)
        self.service = VpcV1('2020-06-02', authenticator=authenticator)

        token = self.config.get('token', None)
        token_expiry_time = self.config.get('token_expiry_time', None)
        api_key_type = 'IAM'
        self.iam_token_manager = IBMTokenManager(iam_api_key, api_key_type, token, token_expiry_time)

        headers = {'content-type': 'application/json'}
        default_user_agent = self.session.headers['User-Agent']
        headers['User-Agent'] = default_user_agent + ' {}'.format(self.config['user_agent'])
        self.session.headers.update(headers)

        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

        msg = COMPUTE_CLI_MSG.format('IBM VPC')
        logger.info("{} - Region: {} - Host: {}".format(msg, self.region, self.ip_address))

    def _authorize_session(self):
        self.config['token'], self.config['token_expiry_time'] = self.iam_token_manager.get_token()
        self.session.headers['Authorization'] = 'Bearer ' + self.config['token']

    def get_ssh_credentials(self):
        return self.ssh_credentials

    def get_instance(self):
        url = '/'.join([self.endpoint, 'v1', 'instances', self.instance_id
                        + f'?version={self.config["version"]}&generation={self.config["generation"]}'])
        self._authorize_session()
        res = self.session.get(url)
        return res.json()

    def get_ip_address(self):
        if self.ip_address:
            return self.ip_address
        else:
            if not self.instance_data:
                self.instance_data = self.get_instance()
            network_interface_id = self.instance_data['primary_network_interface']['id']

            url = '/'.join([self.endpoint, 'v1', 'floating_ips'
                            + f'?version={self.config["version"]}&generation={self.config["generation"]}'])
            self._authorize_session()
            res = self.session.get(url)
            floating_ips_info = res.json()

            ip_address = None
            for floating_ip in floating_ips_info['floating_ips']:
                if floating_ip['target']['id'] == network_interface_id:
                    ip_address = floating_ip['address']

            if ip_address is None:
                raise Exception('Could not find the public IP address')

        return ip_address

    def create_instance_action(self, action):
        if action in ['start', 'reboot']:
            expected_status = 'running'
        elif action == 'stop':
            expected_status = 'stopped'
        else:
            msg = 'An error occurred cant create instance action \"{}\"'.format(action)
            raise Exception(msg)

        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id'],
                        f'actions?version={self.config["version"]}&generation={self.config["generation"]}'])
        self._authorize_session()
        res = self.session.post(url, json={'type': action})
        resp_text = res.json()

        if res.status_code != 201:
            msg = 'An error occurred creating instance action {}: {}'.format(action, resp_text['errors'])
            raise Exception(msg)

        self.instance_data = self.get_instance()
        while self.instance_data['status'] != expected_status:
            time.sleep(1)
            self.instance_data = self.get_instance()

    def _generate_name(self, r_type):
        return "kpavel-" + namegenerator.gen() + "-" + r_type


    def _create_instance(self):
        security_group_identity_model = {'id': 'r006-2d3cc459-bb8b-4ec6-a5fb-28e60c9f7d7b'}
        subnet_identity_model = {'id': '0737-bbc80a8f-d46a-4cc6-8a5a-991daa5fc914'}
        key_identity_model = {'id': "r006-14719c2a-80cf-4043-8018-fa22d4ce1337"}

        volume_prototype_instance_by_image_context_model = {
            'capacity': 100, 'iops': 10000, 'name': self._generate_name('volume'), 'profile': {'name': '10iops-tier'}}
        network_interface_prototype_model = {
            'name': 'eth0', 'subnet': subnet_identity_model, 'security_groups': [security_group_identity_model]}
        volume_attachment_prototype_instance_by_image = {
            'delete_volume_on_instance_delete': True,
            'name': self._generate_name('boot'),
            'volume': volume_prototype_instance_by_image_context_model
        }
        instance_prototype_model = {
            'keys': [key_identity_model], 'name': self._generate_name('instance')}
        instance_prototype_model['profile'] = {'name': "bx2-8x32"}

        instance_prototype_model['resource_group'] = {
            'id': "8145289ddf7047ea93fd2835de391f43"}
        instance_prototype_model['vpc'] = {'id': "r006-afdd7b5d-059f-413f-a319-c0a38ef46824"}
        instance_prototype_model['image'] = {'id': "r006-988caa8b-7786-49c9-aea6-9553af2b1969"}
        instance_prototype_model['zone'] = {'name': "us-south-3"}

        instance_prototype_model['boot_volume_attachment'] = volume_attachment_prototype_instance_by_image
        instance_prototype_model['primary_network_interface'] = network_interface_prototype_model

        response = self.service.create_instance(instance_prototype_model)
        return response.result
        
    def _create_and_attach_floating_ip(self, instance):
        # allocate new floating ip
        floating_ip_prototype_model = {}
        floating_ip_prototype_model['name'] = self._generate_name('fip')
        floating_ip_prototype_model['zone'] = {'name': "us-south-3"}
        floating_ip_prototype_model['resource_group'] = {'id': "8145289ddf7047ea93fd2835de391f43"}

        response = self.service.create_floating_ip(floating_ip_prototype_model)
        floating_ip = response.result
        
        # attach floating ip
        response = self.service.add_instance_network_interface_floating_ip(
            instance['id'], instance['network_interfaces'][0]['id'], floating_ip['id'])

        return floating_ip

    def _delete_instance(self, instance, floating_ip):
        # delete vm instance
        self.service.delete_instance(instance['id'])
        print("instance {} been deleted".format(instance['name']))

        # delete floating ip
        self.service.delete_floating_ip(floating_ip['id'])
        print("floating ip {} been deleted".format(floating_ip['address']))

    def start(self):
        logger.info("Starting VM instance")
        self.create_instance_action('start')
        logger.debug("VM instance started successfully")

    def create(self):
        logger.info("Creating VM instance")
        
        instance = self._create_instance()
        floating_ip = self._create_and_attach_floating_ip(instance)
        logger.debug("VM instance created successfully")
        self.instance_id = instance['id']
        self.config['instance_id'] = instance['id']

        return instance['id'], floating_ip

    def stop(self):
        logger.info("Stopping VM instance")
        self.create_instance_action('stop')
        logger.debug("VM instance stopped successfully")

    def get_runtime_key(self, runtime_name):
        runtime_key = os.path.join(self.name, self.ip_address,
                                   self.instance_id,
                                   runtime_name.strip("/"))

        return runtime_key
