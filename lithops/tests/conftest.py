import os
import pytest
import logging
from lithops.config import (
    default_config,
    load_yaml_config
)

logger = logging.getLogger(__name__)

TESTS_PREFIX = '__lithops.test'


def pytest_addoption(parser):
    parser.addoption("--config", metavar="", default=None, help="path to lithops config file")
    parser.addoption("--backend", metavar="", default=None, help="compute backend")
    parser.addoption("--storage", metavar="", default=None, help="storage backend")
    parser.addoption("--region", metavar="", default=None, help="region")


@pytest.fixture(scope="session", autouse=True)
def setup_global(request):
    config = request.config
    config_file = config.getoption("--config")
    backend = config.getoption("--backend")
    storage = config.getoption("--storage")
    region = config.getoption("--region")

    config_data = None

    if config_file:
        if os.path.exists(config_file):
            config_data = load_yaml_config(config_file)
        else:
            raise FileNotFoundError(f"The provided config file '{config_file}' does not exist")

    config_ow = {'lithops': {}, 'backend': {}}
    config_ow['lithops']['log_level'] = 'DEBUG'
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow['lithops']['backend'] = backend
    if region:
        config_ow['backend']['region'] = region

    lithops_config = default_config(config_data=config_data, config_overwrite=config_ow)
    pytest.lithops_config = lithops_config
