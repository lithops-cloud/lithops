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
import json
import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import httplib2
import google.auth
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from lithops.version import __version__
from lithops.util.ssh_client import SSHClient, ssh_boot_status_message
from lithops.constants import COMPUTE_CLI_MSG, CACHE_DIR
from lithops.config import load_yaml_config, dump_yaml_config
from lithops.standalone.utils import (
    StandaloneMode,
    CLOUD_CONFIG_WORKER,
    CLOUD_CONFIG_WORKER_PK,
    get_host_setup_script,
)
from lithops.standalone import LithopsValidationError


logger = logging.getLogger(__name__)

INSTANCE_START_TIMEOUT = 180
UBUNTU_OS_PROJECT = 'ubuntu-os-cloud'
UBUNTU_LTS_FAMILIES = (
    'ubuntu-2404-lts-amd64',
    'ubuntu-2204-lts',
)
DEFAULT_UBUNTU_SOURCE_IMAGE = (
    'projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64'
)
DEFAULT_LITHOPS_IMAGE_NAME = 'lithops-ubuntu-2404-lts-amd64-server'

# Scopes for the SA attached to master/worker VMs (GCS, etc. via metadata credentials).
GCE_INSTANCE_SCOPES = ['https://www.googleapis.com/auth/cloud-platform']


class GCPComputeEngineBackend:

    def __init__(self, config, mode):
        logger.debug("Creating GCP Compute Engine client")
        self.name = 'gcp_compute_engine'
        self.config = config
        self.mode = mode
        self.project_name = self.config['project_name']
        self.zone = self.config['zone']
        self.region = self.config.get('region') or '-'.join(self.zone.split('-')[:-1])
        self.credentials_path = self.config.get('credentials_path')

        suffix = 'vm' if self.mode == StandaloneMode.CONSUME.value else 'vpc'
        self.cache_dir = os.path.join(CACHE_DIR, self.name)
        self.cache_file = os.path.join(self.cache_dir, f'{self.project_name}_{self.region}_{suffix}_data')
        self.gce_data = {}
        self.vpc_data_type = 'provided' if 'network_name' in self.config else 'created'
        self.ssh_data_type = 'provided' if 'ssh_key_filename' in self.config else 'created'
        self.network_name = self.config.get('network_name')
        self.network_key = None

        self.compute_client = self._create_compute_client()
        self._resolve_service_account_email()

        self.master = None
        self.workers = []
        self.instance_types = {}

        msg = COMPUTE_CLI_MSG.format('GCP Compute Engine')
        logger.info(f"{msg} - Zone: {self.zone} - Project: {self.project_name}")

    def _resolve_service_account_email(self):
        """
        VMs use the GCE metadata service for GCS credentials (not the laptop key file).
        Attach the same service account as gcp.credentials_path when creating instances.
        """
        if self.config.get('service_account'):
            self.config['service_account_email'] = self.config['service_account']
            logger.debug(
                f'VM service account (from config): {self.config["service_account_email"]}'
            )
            return

        if self.credentials_path and os.path.isfile(self.credentials_path):
            with open(self.credentials_path) as f:
                sa_data = json.load(f)
            email = sa_data.get('client_email')
            if email:
                self.config['service_account_email'] = email
                logger.debug(
                    f'VM service account (from credentials_path): {email}'
                )
                return

        try:
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            email = getattr(credentials, 'service_account_email', None)
            if email:
                self.config['service_account_email'] = email
                logger.debug(f'VM service account (from ADC): {email}')
                return
        except Exception:
            pass

        logger.warning(
            'No service account resolved for GCE VMs. Workers/master cannot access GCS '
            'via metadata unless you set gcp_compute_engine.service_account or '
            'gcp.credentials_path.'
        )

    def _wait_operation(self, operation_name, scope='zone'):
        while True:
            if scope == 'zone':
                op = self.compute_client.zoneOperations().get(
                    project=self.project_name, zone=self.zone, operation=operation_name
                ).execute()
            elif scope == 'region':
                op = self.compute_client.regionOperations().get(
                    project=self.project_name, region=self.region, operation=operation_name
                ).execute()
            else:
                op = self.compute_client.globalOperations().get(
                    project=self.project_name, operation=operation_name
                ).execute()

            if op['status'] == 'DONE':
                if 'error' in op:
                    raise Exception(op['error'])
                return
            time.sleep(2)

    def _load_gce_data(self):
        self.gce_data = load_yaml_config(self.cache_file)
        if self.gce_data and 'network_name' in self.gce_data:
            self.network_name = self.gce_data['network_name']
            self.network_key = self.gce_data.get('network_key')

    def _dump_gce_data(self):
        dump_yaml_config(self.cache_file, self.gce_data)

    def _delete_vpc_data(self):
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)

    def _resource_exists(self, getter):
        try:
            getter()
            return True
        except HttpError as e:
            if getattr(e.resp, 'status', None) == 404:
                return False
            raise

    def _create_network(self):
        if 'network_name' in self.config:
            logger.debug(
                f'Using user-provided network {self.config["network_name"]} '
                f'(subnet {self.config.get("subnet_name", "default")})'
            )
            return

        if 'network_name' in self.gce_data:
            self.config['network_name'] = self.gce_data['network_name']
            self.config['subnet_name'] = self.gce_data['subnet_name']
            self.config['firewall_name'] = self.gce_data['firewall_name']
            self.config['internal_firewall_name'] = self.gce_data.get('internal_firewall_name')
            self.network_name = self.config['network_name']
            logger.debug(f'Using existing network {self.config["network_name"]}')
            logger.debug(
                f'Using existing subnet {self.config["subnet_name"]} in region {self.region}'
            )
            logger.debug(f'Using existing firewall {self.config["firewall_name"]} (SSH)')
            if self.config.get('internal_firewall_name'):
                logger.debug(
                    f'Using existing firewall {self.config["internal_firewall_name"]} '
                    f'(internal ports 8080/8081/6379/22)'
                )
            if self.gce_data.get('router_name'):
                self.config['router_name'] = self.gce_data['router_name']
                self.config['nat_name'] = self.gce_data.get('nat_name')
                logger.debug(
                    f'Using existing Cloud NAT router {self.config["router_name"]} '
                    f'(NAT {self.config.get("nat_name")})'
                )
            else:
                self._create_cloud_nat()
                self.gce_data['router_name'] = self.config.get('router_name')
                self.gce_data['nat_name'] = self.config.get('nat_name')
                self._dump_gce_data()
            return

        self.network_name = f'lithops-net-{str(uuid.uuid4())[-6:]}'
        assert re.match("^[a-z0-9-]*$", self.network_name), f'Network name "{self.network_name}" not valid'
        self.network_key = self.network_name[-6:]
        subnet_name = f'{self.network_name}-subnet'
        firewall_name = f'{self.network_name}-fw'

        logger.debug(
            f'Creating VPC network {self.network_name} '
            f'(CIDR {self.config["network_cidr"]})'
        )
        body = {
            'name': self.network_name,
            'autoCreateSubnetworks': False
        }
        op = self.compute_client.networks().insert(project=self.project_name, body=body).execute()
        self._wait_operation(op['name'], scope='global')

        logger.debug(
            f'Creating subnet {subnet_name} in {self.region} '
            f'(CIDR {self.config["subnet_cidr"]})'
        )
        body = {
            'name': subnet_name,
            'ipCidrRange': self.config['subnet_cidr'],
            'network': f'projects/{self.project_name}/global/networks/{self.network_name}',
            'region': self.region,
            'privateIpGoogleAccess': True,
        }
        op = self.compute_client.subnetworks().insert(
            project=self.project_name, region=self.region, body=body
        ).execute()
        self._wait_operation(op['name'], scope='region')

        logger.debug(f'Creating firewall {firewall_name} (SSH tcp/22 from internet)')
        body = {
            'name': firewall_name,
            'network': f'projects/{self.project_name}/global/networks/{self.network_name}',
            'sourceRanges': ['0.0.0.0/0'],
            'allowed': [{'IPProtocol': 'tcp', 'ports': ['22']}]
        }
        op = self.compute_client.firewalls().insert(project=self.project_name, body=body).execute()
        self._wait_operation(op['name'], scope='global')

        internal_fw_name = f'{self.network_name}-internal-fw'
        logger.debug(
            f'Creating firewall {internal_fw_name} '
            f'(internal tcp 8080/8081/6379/22 from {self.config["network_cidr"]})'
        )
        body = {
            'name': internal_fw_name,
            'network': f'projects/{self.project_name}/global/networks/{self.network_name}',
            'sourceRanges': [self.config['network_cidr']],
            'allowed': [{'IPProtocol': 'tcp', 'ports': ['8080', '8081', '6379', '22']}]
        }
        op = self.compute_client.firewalls().insert(project=self.project_name, body=body).execute()
        self._wait_operation(op['name'], scope='global')

        self.config['network_name'] = self.network_name
        self.config['subnet_name'] = subnet_name
        self.config['firewall_name'] = firewall_name
        self.config['internal_firewall_name'] = internal_fw_name

        self._create_cloud_nat()
        logger.debug(
            f'VPC setup complete: network={self.network_name}, '
            f'subnet={subnet_name}, router={self.config.get("router_name")}'
        )

    def _create_cloud_nat(self):
        """
        Provision Cloud NAT so private worker VMs can reach the internet
        (same role as IBM VPC public gateway / AWS NAT for private subnets).
        The master keeps an ephemeral external IP for SSH from the client.
        """
        if 'router_name' in self.config:
            return

        network_name = self.network_name or self.config.get('network_name')
        subnet_name = self.config.get('subnet_name')
        if not network_name or not subnet_name:
            return

        router_name = f'{network_name}-router'
        nat_name = f'{network_name}-nat'

        if self._resource_exists(
            lambda: self.compute_client.routers().get(
                project=self.project_name,
                region=self.region,
                router=router_name,
            ).execute()
        ):
            logger.debug(f'Using existing Cloud NAT router {router_name}')
            self.config['router_name'] = router_name
            self.config['nat_name'] = nat_name
            return

        logger.debug(
            f'Creating Cloud NAT router {router_name} with NAT {nat_name} '
            f'on subnet {subnet_name} (worker outbound internet)'
        )
        network_url = (
            f'https://www.googleapis.com/compute/v1/projects/{self.project_name}'
            f'/global/networks/{network_name}'
        )
        region_url = (
            f'https://www.googleapis.com/compute/v1/projects/{self.project_name}'
            f'/regions/{self.region}'
        )
        subnet_url = (
            f'https://www.googleapis.com/compute/v1/projects/{self.project_name}'
            f'/regions/{self.region}/subnetworks/{subnet_name}'
        )
        body = {
            'name': router_name,
            'network': network_url,
            'region': region_url,
            'nats': [{
                'name': nat_name,
                'natIpAllocateOption': 'AUTO_ONLY',
                'sourceSubnetworkIpRangesToNat': 'LIST_OF_SUBNETWORKS',
                'subnetworks': [{
                    'name': subnet_url,
                    'sourceIpRangesToNat': ['ALL_IP_RANGES'],
                }],
            }],
        }
        op = self.compute_client.routers().insert(
            project=self.project_name,
            region=self.region,
            body=body,
        ).execute()
        self._wait_operation(op['name'], scope='region')

        self.config['router_name'] = router_name
        self.config['nat_name'] = nat_name

    def _create_ssh_key(self):
        """
        Creates a new SSH key pair on the client (same pattern as AWS EC2 / IBM VPC).
        Used for Lithops client -> master SSH; workers use the master lithops_id_rsa key.
        """
        if 'ssh_key_filename' in self.gce_data and os.path.isfile(self.gce_data['ssh_key_filename']):
            self.config['ssh_key_filename'] = self.gce_data['ssh_key_filename']
            return

        user_key = os.path.expanduser(self.config.get('ssh_key_filename', '~/.ssh/id_rsa'))
        if os.path.isfile(user_key) and 'lithops-key-' not in os.path.basename(user_key):
            logger.debug(f'Using user-provided SSH key {user_key}')
            self.config['ssh_key_filename'] = user_key
            return

        keyname = f'lithops-key-{str(uuid.uuid4())[-8:]}'
        filename = os.path.join("~", ".ssh", f"{keyname}.{self.name}.id_rsa")
        key_filename = os.path.expanduser(filename)
        if not os.path.isfile(key_filename):
            logger.debug("Generating new ssh key pair")
            os.system(f'ssh-keygen -b 2048 -t rsa -f {key_filename} -q -N ""')
            logger.debug(f"SSH key pair generated: {key_filename}")
        self.config['ssh_key_filename'] = key_filename

    def _load_instance_types(self):
        if 'instance_types' in self.gce_data:
            self.instance_types = self.gce_data['instance_types']
            return

        self.instance_types = {}
        request = self.compute_client.machineTypes().list(
            project=self.project_name, zone=self.zone
        )
        while request is not None:
            response = request.execute()
            for machine_type in response.get('items', []):
                self.instance_types[machine_type['name']] = machine_type.get('guestCpus', 1)
            request = self.compute_client.machineTypes().list_next(
                previous_request=request, previous_response=response
            )

    def _instance_exists(self, instance_name):
        return self._resource_exists(
            lambda: self.compute_client.instances().get(
                project=self.project_name, zone=self.zone, instance=instance_name
            ).execute()
        )

    def _create_master_instance(self):
        """
        Creates the master VM instance
        """
        name = self.config.get('instance_name') or f'lithops-master-{self.network_key}'
        self.master = GCPComputeEngineInstance(
            name, self.config, self.compute_client, public=True
        )
        self.master.instance_type = self.config['master_instance_type']
        self.master.delete_on_dismantle = False
        self.master.get_instance_data()

    def _create_compute_client(self):
        if self.credentials_path and os.path.isfile(self.credentials_path):
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        else:
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )

        http = AuthorizedHttp(credentials, http=httplib2.Http())
        return build('compute', 'v1', http=http, cache_discovery=False)

    def is_initialized(self):
        if self.mode == StandaloneMode.CONSUME.value:
            return True
        return os.path.isfile(self.cache_file)

    def init(self):
        logger.debug(f'Initializing GCP Compute Engine backend ({self.mode} mode)')
        self._load_gce_data()

        if self.mode == StandaloneMode.CONSUME.value:
            instance_name = self.config['instance_name']
            if not self.gce_data or instance_name != self.gce_data.get('master_name'):
                self.gce_data = {
                    'mode': self.mode,
                    'vpc_data_type': 'provided',
                    'ssh_data_type': 'provided',
                    'master_name': instance_name,
                    'master_id': instance_name,
                }

            self.config['instance_name'] = self.gce_data['master_name']
            self._create_master_instance()
            self._dump_gce_data()
            return
        
        elif self.mode in [StandaloneMode.CREATE.value, StandaloneMode.REUSE.value]:
            self._create_network()
            self._create_ssh_key()
            self._request_source_image()
            if 'instance_name' not in self.config:
                self.config['instance_name'] = f'lithops-master-{self.network_key}'
            self._create_master_instance()
            self._load_instance_types()
            self.gce_data = {
                'mode': self.mode,
                'vpc_data_type': self.vpc_data_type,
                'ssh_data_type': self.ssh_data_type,
                'master_name': self.master.name,
                'master_id': self.network_key,
                'network_name': self.config['network_name'],
                'network_key': self.network_key,
                'subnet_name': self.config['subnet_name'],
                'firewall_name': self.config['firewall_name'],
                'internal_firewall_name': self.config['internal_firewall_name'],
                'router_name': self.config.get('router_name'),
                'nat_name': self.config.get('nat_name'),
                'ssh_key_filename': self.config['ssh_key_filename'],
                'source_image': self.config['source_image'],
                'instance_types': self.instance_types,
            }
            self._dump_gce_data()

    @staticmethod
    def _is_default_ubuntu_source_image(source_image):
        if not source_image:
            return True
        return (
            source_image == DEFAULT_UBUNTU_SOURCE_IMAGE
            or source_image.endswith('/family/ubuntu-2404-lts-amd64')
            or source_image.endswith('/family/ubuntu-2204-lts')
        )

    def _project_image_ref(self, image_name):
        return f'projects/{self.project_name}/global/images/{image_name}'

    def _get_project_image(self, image_name):
        try:
            return self.compute_client.images().get(
                project=self.project_name, image=image_name
            ).execute()
        except HttpError as err:
            if getattr(err.resp, 'status', None) == 404:
                return None
            raise

    def _request_source_image(self):
        """
        Requests the default image if not provided
        """
        if not self._is_default_ubuntu_source_image(self.config.get('source_image')):
            return

        if 'source_image' in self.gce_data:
            self.config['source_image'] = self.gce_data['source_image']
            return

        for image in self._iter_project_images(self.project_name):
            if image.get('name') == DEFAULT_LITHOPS_IMAGE_NAME:
                image_ref = self._project_image_ref(DEFAULT_LITHOPS_IMAGE_NAME)
                logger.debug(f'Found default VM image: {DEFAULT_LITHOPS_IMAGE_NAME}')
                self.config['source_image'] = image_ref
                return

        if 'source_image' not in self.config:
            self.config['source_image'] = DEFAULT_UBUNTU_SOURCE_IMAGE

    def _get_boot_disk_source(self, instance_data):
        for disk in instance_data.get('disks', []):
            if disk.get('boot'):
                disk_url = disk.get('source', '')
                if '/disks/' in disk_url:
                    return disk_url.split('/disks/')[-1]
        raise Exception(f'Boot disk not found for instance {instance_data.get("name")}')

    def _wait_image_ready(self, image_name, timeout=600):
        start = time.time()
        while time.time() - start < timeout:
            image = self._get_project_image(image_name)
            if image:
                status = image.get('status', 'UNKNOWN')
                logger.debug(f'VM Image is being created. Current status: {status}')
                if status == 'READY':
                    return image
                if status == 'FAILED':
                    raise Exception(
                        f"VM image '{image_name}' creation failed: {image}"
                    )
            time.sleep(20)
        raise TimeoutError(
            f"VM image '{image_name}' was not ready after {timeout}s"
        )

    def build_image(self, image_name, script_file, overwrite, include, extra_args=[]):
        """
        Builds a new VM Image
        """
        image_name = image_name or DEFAULT_LITHOPS_IMAGE_NAME

        if self._get_project_image(image_name):
            if overwrite:
                self.delete_image(image_name)
            else:
                image_ref = self._project_image_ref(image_name)
                raise Exception(
                    f"The image with name '{image_name}' already exists with ID: "
                    f"'{image_ref}'. Use '--overwrite' or '-o' if you want to overwrite it"
                )

        is_initialized = self.is_initialized()
        self.init()

        try:
            del self.config['source_image']
        except Exception:
            pass
        try:
            del self.gce_data['source_image']
        except Exception:
            pass

        self._request_source_image()

        build_vm = GCPComputeEngineInstance(
            'building-image-' + image_name, self.config, self.compute_client, public=True
        )
        build_vm.instance_type = self.config['master_instance_type']
        build_vm.delete_on_dismantle = False
        build_vm.create(public=True)
        build_vm.wait_ready()

        logger.debug(f"Uploading installation script to {build_vm}")
        remote_script = "/tmp/install_lithops.sh"
        script = get_host_setup_script(lithops_pip_spec='lithops[gcp,redis]')
        build_vm.get_ssh_client().upload_data_to_file(script, remote_script)
        logger.debug("Executing Lithops installation script. Be patient, this process can take up to 3 minutes")
        build_vm.get_ssh_client().run_remote_command(
            f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};"
        )
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
            build_vm.get_ssh_client().run_remote_command(
                f"chmod 777 {remote_script}; sudo {remote_script}; rm {remote_script};"
            )
            logger.debug(f"User script '{script_file}' finsihed")

        logger.debug(f'Stopping {build_vm} before creating VM image')
        build_vm.stop()
        build_vm.wait_stopped()

        instance_data = build_vm.get_instance_data()
        disk_name = self._get_boot_disk_source(instance_data)
        source_disk = f'zones/{self.zone}/disks/{disk_name}'

        op = self.compute_client.images().insert(
            project=self.project_name,
            body={
                'name': image_name,
                'description': 'Lithops Image',
                'sourceDisk': source_disk,
                'labels': {'type': 'lithops-runtime'},
            },
        ).execute()
        self._wait_operation(op['name'], scope='global')

        logger.debug("Starting VM image creation")
        self._wait_image_ready(image_name)

        if not is_initialized:
            while not self.clean(all=True):
                time.sleep(5)
        else:
            build_vm.delete()

        image_ref = self._project_image_ref(image_name)
        logger.info(f"VM Image created. Image ID: {image_ref}")

    def delete_image(self, image_name):
        """
        Deletes a custom GCE image from the project.
        """
        image = self._get_project_image(image_name)
        if not image:
            logger.debug(f"VM Image '{image_name}' does not exist")
            return

        logger.debug(f"Deleting VM Image '{image_name}'")
        op = self.compute_client.images().delete(
            project=self.project_name, image=image_name
        ).execute()
        self._wait_operation(op['name'], scope='global')

        while self._get_project_image(image_name):
            time.sleep(2)
        logger.debug(f"VM Image '{image_name}' successfully deleted")

    @staticmethod
    def _format_image_timestamp(timestamp):
        if not timestamp:
            return 'Unknown'
        try:
            created_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            return timestamp
        return created_at.strftime('%Y-%m-%d %H:%M:%S')

    def _iter_project_images(self, project):
        request = self.compute_client.images().list(project=project)
        while request is not None:
            response = request.execute()
            yield from response.get('items', [])
            request = self.compute_client.images().list_next(
                previous_request=request, previous_response=response
            )

    def list_images(self, **kwargs):
        """
        List Ubuntu LTS image families (latest) and custom Lithops images in the project.
        Returns tuples of (name, image_id, creation_date) like other standalone backends.
        """
        result = set()

        for family in UBUNTU_LTS_FAMILIES:
            try:
                image = self.compute_client.images().getFromFamily(
                    project=UBUNTU_OS_PROJECT, family=family
                ).execute()
            except HttpError as err:
                if getattr(err.resp, 'status', None) == 404:
                    continue
                raise

            created_at = self._format_image_timestamp(image.get('creationTimestamp'))
            family_ref = f'projects/{UBUNTU_OS_PROJECT}/global/images/family/{family}'
            result.add((image['name'], family_ref, created_at))

        for image in self._iter_project_images(self.project_name):
            name = image.get('name', '')
            if 'lithops' not in name.lower():
                continue
            created_at = self._format_image_timestamp(image.get('creationTimestamp'))
            image_ref = f'projects/{self.project_name}/global/images/{name}'
            result.add((name, image_ref, created_at))

        return sorted(result, key=lambda x: x[2], reverse=True)

    def clean(self, **kwargs):
        """
        Clean all the backend resources.
        Returns True when cleanup completed, False if resources are still in use.
        """
        all_clean = kwargs.get('all', False)
        logger.info('Cleaning GCP Compute Engine resources')

        if not self.gce_data:
            self._load_gce_data()

        if self.mode == StandaloneMode.CONSUME.value:
            self._delete_vpc_data()
            return True

        try:
            self._delete_vm_instances(all=all_clean)

            master_name = self.gce_data.get('master_name') or (
                self.master.name if self.master else None
            )
            if master_name:
                master_pk = os.path.join(self.cache_dir, f'{master_name}-id_rsa.pub')
                if all_clean and os.path.isfile(master_pk):
                    os.remove(master_pk)

            if all_clean:
                self._delete_network_resources()
                self._delete_ssh_key()
                self._delete_vpc_data()
            return True
        except HttpError:
            return False

    def _delete_vm_instances(self, all=False):
        """
        Deletes all worker VM instances
        """
        msg = (
            f'Deleting all Lithops worker VMs from {self.network_name}'
            if self.network_name else 'Deleting all Lithops worker VMs'
        )
        logger.info(msg)

        prefixes = (
            ('lithops-worker-', 'lithops-master-', 'building-image-')
            if all else ('lithops-worker-',)
        )

        def get_instance_names():
            instances = self.compute_client.instances().list(
                project=self.project_name, zone=self.zone
            ).execute().get('items', []) or []
            return [
                ins['name'] for ins in instances
                if ins.get('name', '').startswith(prefixes)
            ]

        while True:
            names = get_instance_names()
            if not names:
                break
            for name in names:
                logger.debug(f"Deleting VM instance {name}")
                op = self.compute_client.instances().delete(
                    project=self.project_name, zone=self.zone, instance=name
                ).execute()
                self._wait_operation(op['name'], scope='zone')

    def _delete_network_resources(self):
        """
        Remove Lithops-created VPC resources (reverse order of creation).
        VMs must already be deleted (they hold NICs on the subnet).
        """
        if self.gce_data.get('vpc_data_type') == 'provided':
            return

        if not self.gce_data.get('network_name'):
            logger.debug('No Lithops network in cache; skipping VPC cleanup')
            return

        fw_names = [
            self.gce_data.get('firewall_name'),
            self.gce_data.get('internal_firewall_name')
        ]
        for fw_name in fw_names:
            if not fw_name:
                continue
            try:
                logger.debug(f'Deleting firewall {fw_name}')
                op = self.compute_client.firewalls().delete(
                    project=self.project_name, firewall=fw_name
                ).execute()
                self._wait_operation(op['name'], scope='global')
            except HttpError as e:
                if getattr(e.resp, 'status', None) != 404:
                    raise

        network_name = self.gce_data.get('network_name')
        router_name = self.gce_data.get('router_name') or (
            f'{network_name}-router' if network_name else None
        )
        if router_name:
            try:
                logger.debug(f'Deleting Cloud Router (NAT) {router_name}')
                op = self.compute_client.routers().delete(
                    project=self.project_name,
                    region=self.region,
                    router=router_name,
                ).execute()
                self._wait_operation(op['name'], scope='region')
            except HttpError as e:
                if getattr(e.resp, 'status', None) != 404:
                    raise

        subnet_name = self.gce_data.get('subnet_name')
        if subnet_name:
            try:
                logger.debug(f'Deleting subnet {subnet_name}')
                op = self.compute_client.subnetworks().delete(
                    project=self.project_name, region=self.region, subnetwork=subnet_name
                ).execute()
                self._wait_operation(op['name'], scope='region')
            except HttpError as e:
                if getattr(e.resp, 'status', None) != 404:
                    raise

        if network_name:
            try:
                logger.debug(f'Deleting network {network_name}')
                op = self.compute_client.networks().delete(
                    project=self.project_name, network=network_name
                ).execute()
                self._wait_operation(op['name'], scope='global')
            except HttpError as e:
                if getattr(e.resp, 'status', None) != 404:
                    raise

    def _delete_ssh_key(self):
        if self.gce_data.get('ssh_data_type') == 'provided':
            return
        key_filename = self.gce_data.get('ssh_key_filename')
        if key_filename and "lithops-key-" in key_filename:
            if os.path.isfile(key_filename):
                os.remove(key_filename)
            if os.path.isfile(f"{key_filename}.pub"):
                os.remove(f"{key_filename}.pub")

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

        if include_master and self.master:
            self.master.stop()

    def get_instance(self, name, **kwargs):
        instance = GCPComputeEngineInstance(name, self.config, self.compute_client)
        for key in kwargs:
            if hasattr(instance, key) and kwargs[key] is not None:
                setattr(instance, key, kwargs[key])
        return instance

    def get_worker_instance_type(self):
        return self.config['worker_instance_type']

    def get_worker_cpu_count(self):
        return self.instance_types.get(self.config['worker_instance_type'], 1)

    def create_worker(self, name):
        """
        Creates a new worker VM instance
        """
        if self.mode == StandaloneMode.CONSUME.value:
            raise NotImplementedError(f'{self.name}.create_worker() not available in consume mode')

        worker = GCPComputeEngineInstance(
            name, self.config, self.compute_client, public=False
        )
        worker.instance_type = self.config['worker_instance_type']

        user = worker.ssh_credentials['username']
        pub_key = os.path.join(self.cache_dir, f'{self.master.name}-id_rsa.pub')
        ssh_public_key = None
        user_data = None

        if os.path.isfile(pub_key):
            with open(pub_key, 'r') as pk:
                pk_data = pk.read().strip()
            user_data = CLOUD_CONFIG_WORKER_PK.format(user, pk_data)
            ssh_public_key = pk_data
            worker.ssh_credentials['key_filename'] = '~/.ssh/lithops_id_rsa'
            worker.ssh_credentials.pop('password', None)
        else:
            logger.error(f'Unable to locate {pub_key}')
            worker.ssh_credentials.pop('key_filename', None)
            token = worker.ssh_credentials['password']
            user_data = CLOUD_CONFIG_WORKER.format(user, token)

        worker.create(public=False, user_data=user_data, ssh_public_key=ssh_public_key)
        self.workers.append(worker)

    def get_runtime_key(self, runtime_name, version=__version__):
        runtime = runtime_name.replace('/', '-').replace(':', '-')
        master_id = self.gce_data.get('master_id', self.config.get('instance_name', self.master.name))
        return os.path.join(self.name, version, master_id, runtime)


class GCPComputeEngineInstance:

    def __init__(self, name, config, compute_client, public=False):
        """
        Initialize a GCPComputeEngineInstance.
        VMs with public=True get an external IP (e.g. master or image build VM).
        """
        self.name = name.lower()
        self.config = config
        self.compute_client = compute_client
        self.public = public
        self.project_name = self.config['project_name']
        self.zone = self.config['zone']

        self.ssh_client = None
        self.instance_data = None
        self.instance_id = None
        self.private_ip = None
        self.public_ip = None
        self.delete_on_dismantle = self.config['delete_on_dismantle']
        self.instance_type = self.config['worker_instance_type']
        self.home_dir = '/home/' + self.config['ssh_username']

        self.ssh_credentials = {
            'username': self.config['ssh_username'],
            'password': self.config['ssh_password'],
            'key_filename': self.config.get('ssh_key_filename', '~/.ssh/id_rsa')
        }

    def __str__(self):
        ip = self.public_ip or self.private_ip
        if ip:
            return f'VM instance {self.name} ({ip})'
        return f'VM instance {self.name}'

    def get_ssh_client(self):
        self.get_instance_data()
        if not self.instance_data:
            raise Exception(f'VM instance {self.name} does not exist')

        if self.public:
            if not self.public_ip:
                status = self.get_status()
                if status == 'TERMINATED':
                    self.start()
                else:
                    self._wait_public_ip(timeout=60)
            ip_address = self.public_ip
        else:
            ip_address = self.private_ip

        if not ip_address:
            raise Exception(
                f'No IP address available for {self.name} '
                f'(status={self.get_status()}, public={self.public})'
            )

        if not self.ssh_client or self.ssh_client.ip_address != ip_address:
            self.ssh_client = SSHClient(ip_address, self.ssh_credentials)
        return self.ssh_client

    def del_ssh_client(self):
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None

    def is_ready(self):
        try:
            self.get_ssh_client().run_remote_command('id')
        except LithopsValidationError as err:
            raise err
        except Exception as err:
            ip = self.public_ip or self.private_ip
            logger.debug(
                f'SSH to {ip}: {ssh_boot_status_message(err)}'
            )
            self.del_ssh_client()
            return False
        return True

    def wait_ready(self, timeout=INSTANCE_START_TIMEOUT):
        logger.debug(f'Waiting {self} to become ready')
        start = time.time()
        if self.public:
            self.get_public_ip()
        else:
            self.get_private_ip()
        while (time.time() - start < timeout):
            if self.is_ready():
                return True
            time.sleep(5)
        raise TimeoutError(f'Readiness probe expired on {self}')

    def get_instance_data(self):
        try:
            res = self.compute_client.instances().get(
                project=self.project_name,
                zone=self.zone,
                instance=self.name
            ).execute()
        except HttpError as err:
            if getattr(err.resp, 'status', None) == 404:
                self.instance_data = None
                return None
            raise

        self.instance_data = res
        self.instance_id = str(res.get('id'))

        interfaces = res.get('networkInterfaces', [])
        if interfaces:
            self.private_ip = interfaces[0].get('networkIP')
            access_cfg = interfaces[0].get('accessConfigs', [])
            if access_cfg:
                self.public_ip = access_cfg[0].get('natIP')
        return self.instance_data

    def get_instance_id(self):
        if not self.instance_id:
            self.get_instance_data()
        return self.instance_id

    def get_private_ip(self):
        if not self.private_ip:
            self.get_instance_data()
        return self.private_ip

    def get_public_ip(self):
        if not self.public_ip:
            self.get_instance_data()
        return self.public_ip

    def get_status(self):
        self.get_instance_data()
        return self.instance_data.get('status') if self.instance_data else None

    def is_stopped(self):
        return self.get_status() == 'TERMINATED'

    def wait_stopped(self, timeout=INSTANCE_START_TIMEOUT):
        logger.debug(f'Waiting {self} to become stopped')
        start = time.time()
        while time.time() - start < timeout:
            if self.is_stopped():
                return True
            time.sleep(3)
        raise TimeoutError(f'Stop probe expired on {self}')

    def _wait_public_ip(self, timeout=INSTANCE_START_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            self.get_instance_data()
            if not self.instance_data:
                raise Exception(f'VM instance {self.name} does not exist')
            if self.public_ip:
                return self.public_ip
            time.sleep(2)
        raise TimeoutError(f'Public IP not available for {self.name} after {timeout}s')

    def create(self, public=False, ssh_public_key=None, user_data=None,
               check_if_exists=False, **kwargs):
        if self._exists():
            self.get_instance_data()
            if check_if_exists:
                status = self.get_status()
                if status == 'TERMINATED':
                    logger.debug(f'VM instance {self.name} is stopped, starting')
                    self.start()
                elif status == 'RUNNING':
                    logger.debug(f'VM instance {self.name} already running')
                elif status in ('STAGING', 'PROVISIONING', 'REPAIRING', 'STOPPING'):
                    logger.debug(
                        f'VM instance {self.name} is {status}, waiting until running'
                    )
                    self._wait_until_status('RUNNING')
                return
            logger.debug(f'VM instance {self.name} already exists')
            return

        logger.debug(f'Creating new VM instance {self.name}')

        if ssh_public_key is None and 'key_filename' in self.ssh_credentials:
            pub_path = os.path.expanduser(self.ssh_credentials['key_filename'] + '.pub')
            if os.path.isfile(pub_path):
                with open(pub_path, 'r') as pkf:
                    ssh_public_key = pkf.read().strip()

        network_iface = {
            'subnetwork': (
                f'projects/{self.project_name}/regions/{self.config["region"]}'
                f'/subnetworks/{self.config["subnet_name"]}'
            )
        }
        # Master: external IP for SSH from the Lithops client.
        # Workers: no external IP; outbound internet uses Cloud NAT on the subnet.
        # Use self.public (set in __init__) when create() is called without public=...
        use_public_ip = public or self.public or self.config.get('worker_public_ip', False)
        if use_public_ip:
            network_iface['accessConfigs'] = [{'name': 'External NAT', 'type': 'ONE_TO_ONE_NAT'}]

        body = {
            'name': self.name,
            'machineType': f'zones/{self.zone}/machineTypes/{self.instance_type}',
            'disks': [{
                'boot': True,
                'autoDelete': True,
                'initializeParams': {
                    'sourceImage': self.config['source_image'],
                    'diskSizeGb': str(self.config['boot_disk_size']),
                    'diskType': f'zones/{self.zone}/diskTypes/{self.config["boot_disk_type"]}'
                }
            }],
            'networkInterfaces': [network_iface],
            'labels': {
                'type': 'lithops-runtime'
            }
        }

        metadata_items = []
        if ssh_public_key:
            metadata_items.append({
                'key': 'ssh-keys',
                'value': f'{self.ssh_credentials["username"]}:{ssh_public_key}'
            })
        if user_data:
            metadata_items.append({'key': 'user-data', 'value': user_data})
        if metadata_items:
            body['metadata'] = {'items': metadata_items}

        sa_email = self.config.get('service_account_email')
        if sa_email:
            body['serviceAccounts'] = [{
                'email': sa_email,
                'scopes': GCE_INSTANCE_SCOPES,
            }]
        else:
            logger.warning(
                f'Creating VM {self.name} without a service account; '
                f'GCS access from the VM will fail'
            )

        if self.config.get('request_spot_instances', False) and not use_public_ip:
            body['scheduling'] = {
                'provisioningModel': 'SPOT',
                'instanceTerminationAction': 'STOP'
            }
        op = self.compute_client.instances().insert(
            project=self.project_name,
            zone=self.zone,
            body=body
        ).execute()
        self._wait_zone_operation(op['name'])
        self.get_instance_data()

    def _wait_until_status(self, target_status, timeout=INSTANCE_START_TIMEOUT):
        start = time.time()
        last_status = None
        while time.time() - start < timeout:
            status = self.get_status()
            if status != last_status:
                logger.debug(
                    f'VM instance {self.name} status: {status} '
                    f'(waiting for {target_status})'
                )
                last_status = status
            if status == target_status:
                return status
            time.sleep(2)
        raise TimeoutError(
            f'{self.name} did not reach status {target_status} (last: {self.get_status()})'
        )

    def start(self):
        status = self.get_status()
        if status == 'RUNNING':
            logger.debug(f'VM instance {self.name} already running')
            if self.public and not self.public_ip:
                self._wait_public_ip(timeout=60)
            return

        logger.debug(f'Starting VM instance {self.name}')
        op = self.compute_client.instances().start(
            project=self.project_name, zone=self.zone, instance=self.name
        ).execute()
        self._wait_zone_operation(op['name'])
        logger.debug(f'VM instance {self.name} start operation completed')
        self.del_ssh_client()
        self.public_ip = None
        self._wait_until_status('RUNNING')
        if self.public:
            self._wait_public_ip()
        ip = self.public_ip or self.private_ip
        logger.debug(f'VM instance {self.name} started ({ip})')

    def stop(self):
        if self.delete_on_dismantle:
            return self.delete()
        op = self.compute_client.instances().stop(
            project=self.project_name, zone=self.zone, instance=self.name
        ).execute()
        self._wait_zone_operation(op['name'])

    def delete(self):
        op = self.compute_client.instances().delete(
            project=self.project_name, zone=self.zone, instance=self.name
        ).execute()
        self._wait_zone_operation(op['name'])

    def validate_capabilities(self):
        pass

    def _exists(self):
        try:
            self.compute_client.instances().get(
                project=self.project_name, zone=self.zone, instance=self.name
            ).execute()
            return True
        except HttpError as e:
            if getattr(e.resp, 'status', None) == 404:
                return False
            raise

    def _wait_zone_operation(self, operation_name, timeout=INSTANCE_START_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            op = self.compute_client.zoneOperations().get(
                project=self.project_name, zone=self.zone, operation=operation_name
            ).execute()
            if op['status'] == 'DONE':
                if 'error' in op:
                    raise Exception(op['error'])
                return
            time.sleep(2)
        raise TimeoutError(
            f'Zone operation {operation_name} timed out after {timeout}s'
        )
