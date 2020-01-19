import os
import tempfile

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP)


def load_config(config_data):
    if 'localhost' not in config_data:
        config_data['localhost'] = {}
