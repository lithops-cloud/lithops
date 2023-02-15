import os
from pathlib import Path
import logging

from ibm_cloud_sdk_core import ApiException

DEFAULT_KEY_NAME = "default-ssh-key"

logger = logging.getLogger(__name__)


def _generate_keypair(keyname):
    """Returns newly generated public ssh-key's contents and private key's path"""
    home = str(Path.home())
    filename = f"{home}{os.sep}.ssh{os.sep}id.rsa.{keyname}"
    try:
        os.remove(filename)
    except Exception:
        pass

    os.system(f'ssh-keygen -b 2048 -t rsa -f {filename} -q -N ""')
    logger.debug(f"\n\n\033[92mSSH key pair been generated\n")
    logger.debug(f"private key: {os.path.abspath(filename)}")
    logger.debug(f"public key {os.path.abspath(filename)}.pub\033[0m")
    with open(f"{filename}.pub", "r") as file:
        ssh_key_data = file.read()
    ssh_key_path = os.path.abspath(filename)
    return ssh_key_data, ssh_key_path


def _get_ssh_key(ibm_vpc_client, name):
    """Returns ssh key matching specified name, stored in the VPC associated with the vpc_client"""
    for key in ibm_vpc_client.list_keys().result["keys"]:
        if key["name"] == name:
            return key


def _register_ssh_key(ibm_vpc_client, resource_group_id):

    keyname = DEFAULT_KEY_NAME

    ssh_key_data, ssh_key_path = _generate_keypair(keyname)

    response = None
    try:  # regardless of the above, try registering an ssh-key
        response = ibm_vpc_client.create_key(public_key=ssh_key_data, name=keyname, resource_group={"id": resource_group_id}, type="rsa")
    except ApiException as e:
        logger.error(e)

        if "Key with name already exists" in e.message and keyname == DEFAULT_KEY_NAME:
            key = _get_ssh_key(ibm_vpc_client, DEFAULT_KEY_NAME)
            ibm_vpc_client.delete_key(id=key["id"])
            response = ibm_vpc_client.create_key(
                public_key=ssh_key_data, name=keyname, resource_group={"id": resource_group_id}, type="rsa"
            )
        else:
            if "Key with fingerprint already exists" in e.message:
                logger.error("Can't register an SSH key with the same fingerprint")
            raise  (e)# can't continue the configuration process without a valid ssh key

    logger.debug(f"\033[92mnew SSH key {keyname} been registered in vpc\033[0m")

    result = response.get_result()
    return result["name"], result["id"], ssh_key_path


DEPENDENCIES = {"ibm_vpc": {"resource_group_id": None}}


def create_default_ssh_key(ibm_vpc_client, resource_group_id):

    # if exist with same name - override
    _, key_id, ssh_key_path = _register_ssh_key(ibm_vpc_client, resource_group_id)

    return key_id, ssh_key_path, "root"
