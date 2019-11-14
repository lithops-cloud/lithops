from psutil import virtual_memory


RUNTIME_NAME_DEFAULT = 'local_machine'
RUNTIME_TIMEOUT_DEFAULT = 600  # 10 minutes


def load_config(config_data):
    config_data['pywren']['runtime'] = RUNTIME_NAME_DEFAULT
    mem = virtual_memory()
    config_data['pywren']['runtime_memory'] = round(mem.total/1024/1024, 2)
    if 'runtime_timeout' not in config_data['pywren']:
        config_data['pywren']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT
    config_data['local'] = {}
