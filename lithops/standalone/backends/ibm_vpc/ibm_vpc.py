import os
import logging
import requests
import time
from lithops.version import __version__
from lithops.util import IBMTokenManager

logger = logging.getLogger(__name__)


class IBMVPCInstanceClient:

    def __init__(self, ibm_vpc_config):
        logger.debug("Creating IBM VPC client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
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

        log_msg = ('Lithops v{} init for IBM Virtual Private Cloud - Host: {} - Region: {}'
                   .format(__version__, self.ip_address, self.region))
        if not self.log_active:
            print(log_msg)
        logger.info("IBM VPC client created successfully")

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

    def start(self):
        logger.info("Starting VM instance")
        self.create_instance_action('start')
        logger.info("VM instance started successfully")

    def stop(self):
        logger.info("Stopping VM instance")
        self.create_instance_action('stop')
        logger.info("VM instance stopped successfully")

    def get_runtime_key(self, runtime_name):
        runtime_key = os.path.join(self.name, self.ip_address,
                                   self.instance_id,
                                   runtime_name.strip("/"))

        return runtime_key
