import logging
import requests

from pywren_ibm_cloud.libs.ibm_utils import IBMIAMAPIKeyManager

logger = logging.getLogger(__name__)


class IBMVPCInstanceClient:

    def __init__(self, ibm_vpc_config, insecure=False, user_agent=None):
        self.config = ibm_vpc_config

        self.session = requests.session()
        if insecure:
            self.session.verify = False

        iam_api_key = self.config.get('iam_api_key')
        token = self.config.get('token', None)
        token_expiry_time = self.config.get('token_expiry_time', None)
        self.ibm_iam_api_key_manager = IBMIAMAPIKeyManager('docker', iam_api_key, token, token_expiry_time)

        headers = {'content-type': 'application/json'}
        if user_agent:
            default_user_agent = self.session.headers['User-Agent']
            headers['User-Agent'] = default_user_agent + ' {}'.format(user_agent)
        self.session.headers.update(headers)

        adapter = requests.adapters.HTTPAdapter()
        self.session.mount('https://', adapter)

    def _authorize_session(self):
        self.config['token'], self.config['token_expiry_time'] = self.ibm_iam_api_key_manager.get_token()
        self.session.headers['Authorization'] = 'Bearer ' + self.config['token']

    def get_instance(self):
        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id']
                        + f'?version={self.config["version"]}&generation={self.config["generation"]}'])
        self._authorize_session()
        res = self.session.get(url)
        return res.json()

    def create_instance_action(self, type):
        if type == 'start':
            expected_status = 'starting'
        elif type == 'stop':
            expected_status = 'stopping'
        elif type == 'reboot':
            expected_status = 'restarting'
        else:
            msg = 'An error occurred cant create instance action \"{}\"'.format(type)
            raise Exception(msg)

        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id'],
                        f'actions?version={self.config["version"]}&generation={self.config["generation"]}'])
        data = {'type': type, 'force': True}
        self._authorize_session()
        res = self.session.put(url, json=data)
        resp_text = res.json()

        if res.status_code != 200:
            msg = 'An error occurred creating instance action {}: {}'.format(type, resp_text['error'])
            raise Exception(msg)

        instance = self.get_instance()
        if instance['status'] != expected_status:
            msg = 'An error occurred instance status \"{}\" does not match with expected status \"{}\"'.format(
                instance['status'], expected_status)
            raise Exception(msg)

        logger.debug("Created instance action {} successfully".format(type))
