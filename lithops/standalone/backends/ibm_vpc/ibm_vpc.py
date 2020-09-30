import logging
import requests
import time

from lithops.libs.ibm_utils import IBMIAMAPIKeyManager

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

        self.soft_dismantle_timeout = self.config.get('soft_dismantle_timeout', 300) # if not specified, 5 minutes to dismantle after last completed
        self.hard_dismantle_timeout = self.config.get('hard_dismantle_timeout', 10800) # if not specified, 3 hours to dismantle after last invoked

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
        if type in ['start', 'reboot']:
            expected_status = 'running'
        elif type == 'stop':
            expected_status = 'stopped'
        else:
            msg = 'An error occurred cant create instance action \"{}\"'.format(type)
            raise Exception(msg)

        url = '/'.join([self.config['endpoint'], 'v1', 'instances', self.config['instance_id'],
                        f'actions?version={self.config["version"]}&generation={self.config["generation"]}'])
        self._authorize_session()
        res = self.session.post(url, json={'type': type})
        resp_text = res.json()

        if res.status_code != 201:
            msg = 'An error occurred creating instance action {}: {}'.format(type, resp_text['errors'])
            raise Exception(msg)

        while self.get_instance()['status'] != expected_status:
            time.sleep(1)

        logger.debug("Created instance action {} successfully".format(type))

    def setup(self, readiness_probe=None):
        if readiness_probe():
            return
        else:
            self.create_instance_action('start')
            start_timeout = self.config.get('start_timeout', 300)
            logger.info("Waiting for compute backend to become ready")
            if not readiness_probe(timeout=start_timeout):
                raise Exception("Failed to make the compute ready")

    def dismantle(self):
        self.create_instance_action('stop')
