#
# Copyright Cloudlab URV 2020
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
import time
import click
import logging
import shutil

import lithops
from lithops.scripts.tests import print_help, run_tests
from lithops.utils import setup_logger, verify_runtime_name
from lithops.config import get_mode, default_config, extract_storage_config,\
    extract_serverless_config, extract_standalone_config,\
    extract_localhost_config
from lithops.constants import CACHE_DIR, LITHOPS_TEMP_DIR, RUNTIMES_PREFIX,\
    JOBS_PREFIX, LOCALHOST, SERVERLESS, STANDALONE, FN_LOG_FILE, LOGS_DIR
from lithops.storage import InternalStorage
from lithops.serverless import ServerlessHandler
from lithops.storage.utils import clean_bucket
from lithops.standalone.standalone import StandaloneHandler
from lithops.localhost.localhost import LocalhostHandler


logger = logging.getLogger(__name__)


@click.group('lithops_cli')
@click.version_option()
def lithops_cli():
    pass


@lithops_cli.command('clean')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--mode', '-m', default=None,
              type=click.Choice([SERVERLESS, LOCALHOST, STANDALONE], case_sensitive=True),
              help='execution mode')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def clean(config, mode, backend, storage, debug):
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_logger(log_level)
    logger.info('Cleaning all Lithops information')

    mode = mode or get_mode(config)
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    config = default_config(config, config_ow)

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    mode = config['lithops']['mode'] if not mode else mode
    if mode == LOCALHOST:
        compute_config = extract_localhost_config(config)
        compute_handler = LocalhostHandler(compute_config)
    elif mode == SERVERLESS:
        compute_config = extract_serverless_config(config)
        compute_handler = ServerlessHandler(compute_config, storage_config)
    elif mode == STANDALONE:
        compute_config = extract_standalone_config(config)
        compute_handler = StandaloneHandler(compute_config)

    compute_handler.clean()

    # Clean object storage temp dirs
    storage = internal_storage.storage
    clean_bucket(storage, storage_config['bucket'], RUNTIMES_PREFIX, sleep=1)
    clean_bucket(storage, storage_config['bucket'], JOBS_PREFIX, sleep=1)

    # Clean localhost executor temp dirs
    shutil.rmtree(LITHOPS_TEMP_DIR, ignore_errors=True)
    # Clean local lithops cache
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


@lithops_cli.command('test')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--mode', '-m', default=None,
              type=click.Choice([SERVERLESS, LOCALHOST, STANDALONE], case_sensitive=True),
              help='execution mode')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def test_function(config, mode, backend, storage, debug):
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_logger(log_level)

    def hello(name):
        return 'Hello {}!'.format(name)

    fexec = lithops.FunctionExecutor(config=config, mode=mode,
                                     backend=backend, storage=storage)
    fexec.call_async(hello, 'World')
    result = fexec.get_result()
    print()
    if result == 'Hello World!':
        print(result, 'Lithops is working as expected :)')
    else:
        print(result, 'Something went wrong :(')
    print()


@lithops_cli.command('verify')
@click.option('--test', '-t', default='all', help='run a specific test, type "-t help" for tests list')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--mode', '-m', default=None,
              type=click.Choice([SERVERLESS, LOCALHOST, STANDALONE], case_sensitive=True),
              help='execution mode')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def verify(test, config, mode, backend, storage, debug):
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_logger(log_level)

    if test == 'help':
        print_help()
    else:
        run_tests(test, config, mode, backend, storage)


# /---------------------------------------------------------------------------/
#
# lithops logs
#
# /---------------------------------------------------------------------------/

@click.group('logs')
@click.pass_context
def logs(ctx):
    pass


@logs.command('poll')
def poll():
    logging.basicConfig(level=logging.DEBUG)

    def follow(file):
        line = ''
        while True:
            if not os.path.isfile(FN_LOG_FILE):
                break
            tmp = file.readline()
            if tmp:
                line += tmp
                if line.endswith("\n"):
                    yield line
                    line = ''
            else:
                time.sleep(1)

    while True:
        if os.path.isfile(FN_LOG_FILE):
            for line in follow(open(FN_LOG_FILE, 'r')):
                print(line, end='')
        else:
            time.sleep(1)


@logs.command('get')
@click.argument('job_key')
def get(job_key):
    log_file = os.path.join(LOGS_DIR, job_key+'.log')

    if not os.path.isfile(log_file):
        print('The execution id: {} does not exists in logs'.format(job_key))
        return

    with open(log_file, 'r') as content_file:
        print(content_file.read())


# /---------------------------------------------------------------------------/
#
# lithops runtime
#
# /---------------------------------------------------------------------------/

@click.group('runtime')
@click.pass_context
def runtime(ctx):
    pass


@runtime.command('create')
@click.argument('name')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
@click.option('--timeout', default=None, help='runtime timeout', type=int)
def create(name, storage, backend, memory, timeout, config):
    """ Create a serverless runtime """
    setup_logger(logging.DEBUG)
    logger.info('Creating new lithops runtime: {}'.format(name))

    mode = SERVERLESS
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    config = default_config(config, config_ow)

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)
    mem = memory if memory else compute_config['runtime_memory']
    to = timeout if timeout else compute_config['runtime_timeout']
    runtime_key = compute_handler.get_runtime_key(name, mem)
    runtime_meta = compute_handler.create_runtime(name, mem, timeout=to)

    try:
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)
    except Exception:
        raise("Unable to upload 'preinstalled-modules' file into {}".format(internal_storage.backend))


@runtime.command('build')
@click.argument('name')
@click.option('--file', '-f', default=None, help='file needed to build the runtime')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--backend', '-b', default=None, help='compute backend')
def build(name, file, config, backend):
    """ build a serverless runtime. """
    verify_runtime_name(name)
    setup_logger(logging.DEBUG)

    mode = SERVERLESS
    config_ow = {'lithops': {'mode': mode}}
    if backend:
        config_ow[mode] = {'backend': backend}
    config = default_config(config, config_ow)

    storage_config = extract_storage_config(config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)
    compute_handler.build_runtime(name, file)


@runtime.command('update')
@click.argument('name')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
def update(name, config, backend, storage):
    """ Update a serverless runtime """
    verify_runtime_name(name)
    setup_logger(logging.DEBUG)

    mode = SERVERLESS
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    config = default_config(config, config_ow)

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)

    timeout = compute_config['runtime_memory']
    logger.info('Updating runtime: {}'.format(name))

    runtimes = compute_handler.list_runtimes(name)

    for runtime in runtimes:
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1])
        runtime_meta = compute_handler.create_runtime(runtime[0], runtime[1], timeout)

        try:
            internal_storage.put_runtime_meta(runtime_key, runtime_meta)
        except Exception:
            raise("Unable to upload 'preinstalled-modules' file into {}".format(internal_storage.backend))


@runtime.command('delete')
@click.argument('name')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
def delete(name, config, backend, storage):
    """ delete a serverless runtime """
    verify_runtime_name(name)
    setup_logger(logging.DEBUG)

    mode = SERVERLESS
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    config = default_config(config, config_ow)

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, storage_config)

    runtimes = compute_handler.list_runtimes(name)
    for runtime in runtimes:
        compute_handler.delete_runtime(runtime[0], runtime[1])
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1])
        internal_storage.delete_runtime_meta(runtime_key)


lithops_cli.add_command(runtime)
lithops_cli.add_command(logs)


if __name__ == '__main__':
    lithops_cli()
