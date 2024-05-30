import os
import json

from lithops.serverless.backends.k8s.config import (
    DEFAULT_CONFIG_KEYS,
    DEFAULT_GROUP,
    DEFAULT_VERSION,
    MASTER_NAME,
    MASTER_PORT,
    DOCKERFILE_DEFAULT,
    JOB_DEFAULT,
    POD,
    load_config as original_load_config
)

DEFAULT_ONEKE_CONFIG = """
{
    "name": "OneKE/1",
    "networks_values": [
        {"Public": {"id": "0"}},
        {"Private": {"id": "1"}}
    ],
    "custom_attrs_values": {
        "ONEAPP_VROUTER_ETH0_VIP0": "",
        "ONEAPP_VROUTER_ETH1_VIP0": "",

        "ONEAPP_RKE2_SUPERVISOR_EP": "ep0.eth0.vr:9345",
        "ONEAPP_K8S_CONTROL_PLANE_EP": "ep0.eth0.vr:6443",
        "ONEAPP_K8S_EXTRA_SANS": "localhost,127.0.0.1,ep0.eth0.vr,${vnf.TEMPLATE.CONTEXT.ETH0_IP},k8s.yourdomain.it",

        "ONEAPP_K8S_MULTUS_ENABLED": "NO",
        "ONEAPP_K8S_MULTUS_CONFIG": "",
        "ONEAPP_K8S_CNI_PLUGIN": "cilium",
        "ONEAPP_K8S_CNI_CONFIG": "",
        "ONEAPP_K8S_CILIUM_RANGE": "",

        "ONEAPP_K8S_METALLB_ENABLED": "NO",
        "ONEAPP_K8S_METALLB_CONFIG": "",
        "ONEAPP_K8S_METALLB_RANGE": "",

        "ONEAPP_K8S_LONGHORN_ENABLED": "YES",
        "ONEAPP_STORAGE_DEVICE": "/dev/vdb",
        "ONEAPP_STORAGE_FILESYSTEM": "xfs",

        "ONEAPP_K8S_TRAEFIK_ENABLED": "YES",
        "ONEAPP_VNF_HAPROXY_INTERFACES": "eth0",
        "ONEAPP_VNF_HAPROXY_REFRESH_RATE": "30",
        "ONEAPP_VNF_HAPROXY_LB0_PORT": "9345",
        "ONEAPP_VNF_HAPROXY_LB1_PORT": "6443",
        "ONEAPP_VNF_HAPROXY_LB2_PORT": "443",
        "ONEAPP_VNF_HAPROXY_LB3_PORT": "80",

        "ONEAPP_VNF_DNS_ENABLED": "YES",
        "ONEAPP_VNF_DNS_INTERFACES": "eth1",
        "ONEAPP_VNF_DNS_NAMESERVERS": "1.1.1.1,8.8.8.8",
        "ONEAPP_VNF_NAT4_ENABLED": "YES",
        "ONEAPP_VNF_NAT4_INTERFACES_OUT": "eth0",
        "ONEAPP_VNF_ROUTER4_ENABLED": "YES",
        "ONEAPP_VNF_ROUTER4_INTERFACES": "eth0,eth1"
    }
}
"""

DEFAULT_PRIVATE_VNET = """
NAME    = "private-oneke"
VN_MAD  = "bridge"
AUTOMATIC_VLAN_ID = "YES"
AR = [TYPE = "IP4", IP = "192.168.150.0", SIZE = "51"]
"""

DEFAULT_CONFIG_KEYS = {
    'public_vnet_id': -1,
    'private_vnet_id': -1,
    'oneke_config': DEFAULT_ONEKE_CONFIG,    
    #TODO: Add kube.config file 
}

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_one.zip')

# Overwrite default Dockerfile
DOCKERFILE_DEFAULT = "\n".join(DOCKERFILE_DEFAULT.split('\n')[:-2]) + """
COPY lithops_one.zip .
RUN unzip lithops_one.zip && rm lithops_one.zip
"""

def load_config(config_data):
    if 'oneke_config' in config_data:
        try:
            with open(config_data['oneke_config'], 'r') as f:
                config_data['oneke_config'] = json.load(f)
        except (IOError, json.JSONDecodeError) as err:
            raise Exception(f"Error reading OneKE config file: {err}")
    original_load_config(config_data)