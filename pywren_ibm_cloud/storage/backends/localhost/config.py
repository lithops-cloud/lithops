import tempfile
import os
from pywren_ibm_cloud.config import STORAGE_FOLDER

TEMP = os.path.realpath(tempfile.gettempdir())
STORAGE_BASE_DIR = os.path.join(TEMP, STORAGE_FOLDER)


def load_config(config_data):
    if 'localhost' not in config_data:
        config_data['localhost'] = {}
