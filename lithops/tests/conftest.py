import os
import pytest
import logging
from lithops.config import (
    default_config,
    extract_storage_config,
    load_yaml_config
)
from lithops.storage import Storage

logger = logging.getLogger(__name__)

TESTS_PREFIX = '__lithops.test'


def pytest_addoption(parser):
    parser.addoption("--config", metavar="", default=None, help="path to lithops config file")
    parser.addoption("--backend", metavar="", default=None, help="compute backend")
    parser.addoption("--storage", metavar="", default=None, help="storage backend")
    parser.addoption("--region", metavar="", default=None, help="region")


@pytest.fixture(autouse=True)
def restore_environ():
    """
    Gives every test the environment back as it found it.

    Worker code sets process-wide variables of its own — LITHOPS_WORKER, the
    session id, the monitoring queues — so a test that calls it leaks them
    into every test that runs afterwards, and `monkeypatch.delenv` registers
    no undo for a variable that was not there to begin with. That made the
    outcome depend on the order the files happened to run in
    """
    saved = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(saved)


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
    _clear_tests_prefix(lithops_config)


def _clear_tests_prefix(config):
    """
    Deletes whatever an earlier session left under the tests prefix.

    Every test class removes its own objects on teardown, but a session
    that was interrupted never gets there, and what it left behind then
    turns up in the listings of the next one, which counts words and
    objects and gets a number nobody can explain
    """
    try:
        storage = Storage(storage_config=extract_storage_config(config))
        keys = storage.list_keys(bucket=storage.bucket, prefix=TESTS_PREFIX)
        for key in keys:
            storage.delete_object(bucket=storage.bucket, key=key)
    except Exception:
        # Never fail the session over this: the tests that care clean up
        # after themselves, and this only spares them a dirty start
        logger.warning(
            f'Could not clear the {TESTS_PREFIX} prefix left by an earlier '
            'test session', exc_info=True
        )
        return
    if keys:
        logger.info(
            f'Removed {len(keys)} object(s) left under {TESTS_PREFIX} by an '
            'earlier test session'
        )
