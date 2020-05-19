

def load_config(config_data):
    if 'localhost' not in config_data:
        config_data['localhost'] = {}
