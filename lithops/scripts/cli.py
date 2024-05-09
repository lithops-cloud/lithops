#
# (C) Copyright Cloudlab URV 2020
# (C) Copyright IBM Corp. 2023
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
import shlex
import subprocess as sp
from itertools import cycle
from tabulate import tabulate
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import lithops
from lithops import Storage
from lithops.version import __version__
from lithops.utils import (
    get_mode,
    setup_lithops_logger,
    verify_runtime_name,
    sizeof_fmt
)
from lithops.config import (
    default_config,
    extract_storage_config,
    extract_serverless_config,
    extract_standalone_config,
    extract_localhost_config,
    load_yaml_config
)
from lithops.constants import (
    CACHE_DIR,
    LITHOPS_TEMP_DIR,
    RUNTIMES_PREFIX,
    JOBS_PREFIX,
    LOCALHOST,
    SERVERLESS,
    STANDALONE,
    LOGS_DIR,
    FN_LOG_FILE,
    STANDALONE_BACKENDS
)
from lithops.storage import InternalStorage
from lithops.serverless import ServerlessHandler
from lithops.storage.utils import clean_bucket
from lithops.standalone import StandaloneHandler
from lithops.localhost import LocalhostHandler


logger = logging.getLogger(__name__)


def set_config_ow(backend, storage=None, runtime_name=None, region=None):
    config_ow = {'lithops': {}, 'backend': {}}

    if storage:
        config_ow['lithops']['storage'] = storage

    if backend:
        config_ow['lithops']['backend'] = backend
        config_ow['lithops']['mode'] = get_mode(backend)

    if runtime_name:
        config_ow['backend']['runtime'] = runtime_name

    if region:
        config_ow['backend']['region'] = region

    return config_ow


@click.group('lithops_cli')
@click.version_option()
def lithops_cli():
    pass


@lithops_cli.command('clean')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--all', '-a', is_flag=True, help='delete all, including master VM in case of standalone')
def clean(config, backend, storage, debug, region, all):
    config = load_yaml_config(config) if config else None

    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)
    logger.info('Cleaning all Lithops information')

    config_ow = set_config_ow(backend=backend, storage=storage, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow)
    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    mode = config['lithops']['mode']
    backend = config['lithops']['backend']

    if mode == LOCALHOST:
        compute_config = extract_localhost_config(config)
        compute_handler = LocalhostHandler(compute_config)
    elif mode == SERVERLESS:
        compute_config = extract_serverless_config(config)
        compute_handler = ServerlessHandler(compute_config, internal_storage)
    elif mode == STANDALONE:
        compute_config = extract_standalone_config(config)
        compute_handler = StandaloneHandler(compute_config)

    compute_handler.clean(all=all)

    # Clean object storage temp dirs
    storage = internal_storage.storage
    runtimes_path = RUNTIMES_PREFIX + '/' + backend
    jobs_path = JOBS_PREFIX
    clean_bucket(storage, storage.bucket, runtimes_path, sleep=1)
    clean_bucket(storage, storage.bucket, jobs_path, sleep=1)

    # Clean localhost executor temp dirs
    shutil.rmtree(LITHOPS_TEMP_DIR, ignore_errors=True)
    # Clean local lithops runtime cache
    shutil.rmtree(os.path.join(CACHE_DIR, RUNTIMES_PREFIX, backend), ignore_errors=True)

    logger.info('All Lithops temporary data cleaned')


@lithops_cli.command('test')
@click.option('--config', '-c', default=None, help='Path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='Compute backend')
@click.option('--storage', '-s', default=None, help='Storage backend')
@click.option('--debug', '-d', is_flag=True, help='Debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--test', '-t', default=None, help='Run a specific test. To avoid running similarly named tests '
                                                 'you may prefix the tester with its test class, '
                                                 'e.g. TestAsync::test_call_async'
                                                 'Type "-t help" for the complete tests list')
@click.option('--exitfirst', '-x', is_flag=True, help='Stops test run upon first occurrence of a failed test')
def test(test, config, backend, storage, debug, region, exitfirst):
    import pytest

    dir_path = os.path.dirname(os.path.realpath(__file__))
    tests_path = os.path.abspath(os.path.join(dir_path, '..', 'tests'))

    if test == 'help':
        pytest.main([tests_path, "--collect-only"])
    else:
        cmd_string = [tests_path, "-v"]
        if exitfirst:
            cmd_string.extend(["-x"])
        if debug:
            cmd_string.extend(["-o", "log_cli=true", "--log-cli-level=DEBUG"])
        if config:
            cmd_string.extend(["--config", config])
        if backend:
            cmd_string.extend(["--backend", backend])
        if storage:
            cmd_string.extend(["--storage", storage])
        if region:
            cmd_string.extend(["--region", region])
        if test:
            cmd_string.extend(["-k", test])

        print("Executing lithops tests: pytest " + ' '.join(cmd_string[1:]))

        pytest.main(cmd_string)


@lithops_cli.command('hello')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
def hello(config, backend, storage, debug, region):
    config = load_yaml_config(config) if config else None

    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    try:
        import getpass
        username = getpass.getuser()
    except Exception:
        username = 'World'

    def hello(name):
        return f'Hello {name}!'

    fexec = lithops.FunctionExecutor(
        config=config, backend=backend,
        storage=storage, region=region
    )
    fexec.call_async(hello, username)
    result = fexec.get_result()
    print()
    if result == f'Hello {username}!':
        print(result, 'Lithops is working as expected :)')
    else:
        print(result, 'Something went wrong :(')
    print()


@lithops_cli.command('attach')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option("--start", is_flag=True, default=False, help="Start the master VM if needed.")
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
def attach(config, backend, start, debug, region):
    """Create or attach to a SSH session on Lithops master VM"""
    config = load_yaml_config(config) if config else None

    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('lithops attach method is only available for standalone backends. '
                        f'Please use "lithops attach -b {set(STANDALONE_BACKENDS)}"')

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)

    if not compute_handler.is_initialized():
        logger.info("The backend is not initialized")
        return
    compute_handler.init()
    if not start and not compute_handler.backend.master.is_ready():
        logger.info(f"{compute_handler.backend.master} is stopped")
        return

    if start:
        compute_handler.backend.master.start()

    master_ip = compute_handler.backend.master.get_public_ip()
    user = compute_handler.backend.master.ssh_credentials['username']
    key_file = compute_handler.backend.master.ssh_credentials['key_filename'] or '~/.ssh/id_rsa'
    key_file = os.path.abspath(os.path.expanduser(key_file))

    if not os.path.exists(key_file):
        raise Exception(f'Private key file {key_file} does not exists')

    print(f'Got master VM public IP address: {master_ip}')
    print(f'Loading ssh private key from: {key_file}')
    print('Creating SSH Connection to lithops master VM')
    cmd = ('ssh -o "UserKnownHostsFile=/dev/null" -o "StrictHostKeyChecking=no" '
           f'-i {key_file} {user}@{master_ip}')

    compute_handler.backend.master.wait_ready()

    sp.run(shlex.split(cmd))


# /---------------------------------------------------------------------------/
#
# lithops storage
#
# /---------------------------------------------------------------------------/

@click.group('storage')
@click.pass_context
def storage(ctx):
    pass


@storage.command('put')
@click.argument('filename', type=click.Path(exists=True))
@click.argument('bucket')
@click.option('--key', '-k', default=None, help='object key')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
def upload_file(filename, bucket, key, backend, debug, config):
    config = load_yaml_config(config) if config else None

    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)
    storage = Storage(config=config, backend=backend)

    def upload_file():
        logger.info(f'Uploading file {filename} to {storage.backend}://{bucket}/{key or filename}')
        if storage.upload_file(filename, bucket, key):
            file_size = os.path.getsize(filename)
            logger.info(f'Upload File {filename} - Size: {sizeof_fmt(file_size)} - Ok')
        else:
            logger.error(f'Upload File {filename} - Error')

    with ThreadPoolExecutor() as ex:
        future = ex.submit(upload_file)
        cy = cycle(r"-\|/")
        while not future.done():
            print("Uploading file " + next(cy), end="\r")
            time.sleep(0.1)
        future.result()


@storage.command('get')
@click.argument('bucket')
@click.argument('key')
@click.option('--out', '-o', default=None, help='output filename')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
def download_file(bucket, key, out, backend, debug, config):
    config = load_yaml_config(config) if config else None

    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)
    storage = Storage(config=config, backend=backend)

    def download_file():
        logger.info(f'Downloading file {storage.backend}://{bucket}/{key} to {out or key}')
        if storage.download_file(bucket, key, out):
            file_size = os.path.getsize(out or key)
            logger.info(f'Download File {key} - Size: {sizeof_fmt(file_size)} - Ok')
        else:
            logger.error(f'Download File {key} - Error')

    with ThreadPoolExecutor() as ex:
        future = ex.submit(download_file)
        cy = cycle(r"-\|/")
        while not future.done():
            print("Downloading file " + next(cy), end="\r")
            time.sleep(0.1)
        future.result()


@storage.command('delete')
@click.argument('bucket')
@click.argument('key', required=False)
@click.option('--prefix', '-p', default=None, help='key prefix')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
def delete_object(bucket, key, prefix, backend, debug, config):
    config = load_yaml_config(config) if config else None
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)
    storage = Storage(config=config, backend=backend)

    if key:
        logger.info('Deleting object "{}" from bucket "{}"'.format(key, bucket))
        storage.delete_object(bucket, key)
        logger.info('Object deleted successfully')
    elif prefix:
        objs = storage.list_keys(bucket, prefix)
        logger.info('Deleting {} objects with prefix "{}" from bucket "{}"'.format(len(objs), prefix, bucket))
        storage.delete_objects(bucket, objs)
        logger.info('Object deleted successfully')


@storage.command('list')
@click.argument('bucket')
@click.option('--prefix', '-p', default=None, help='key prefix')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
def list_bucket(prefix, bucket, backend, debug, config):
    config = load_yaml_config(config) if config else None
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)
    storage = Storage(config=config, backend=backend)
    logger.info('Listing objects in bucket {}'.format(bucket))
    objects = storage.list_objects(bucket, prefix=prefix)

    objs = []
    for obj in objects:
        key = obj['Key']
        date = obj['LastModified'].strftime("%b %d %Y %H:%M:%S")
        size = sizeof_fmt(obj['Size'])
        objs.append([key, date, size])

    headers = ['Key', 'Last modified', 'Size']
    print()
    print(tabulate(objs, headers=headers))
    print(f'\nTotal objects: {len(objs)}')


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
def get_logs(job_key):
    log_file = os.path.join(LOGS_DIR, job_key + '.log')

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


@runtime.command('build', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument('name', required=False)
@click.option('--file', '-f', default=None, help='file needed to build the runtime', type=click.Path(exists=True))
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.pass_context
def build(ctx, name, file, config, backend, debug):
    """ build a serverless runtime. """
    # log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(logging.DEBUG)

    verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, runtime_name=name)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != SERVERLESS:
        raise Exception('"lithops runtime build" command is only available for serverless backends')

    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, None)
    runtime_info = compute_handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    compute_handler.build_runtime(runtime_name, file, ctx.args)

    logger.info('Runtime built')


@runtime.command('deploy')
@click.argument('name', required=True)
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
@click.option('--timeout', default=None, help='runtime timeout', type=int)
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def deploy(name, storage, backend, memory, timeout, config, debug):
    """ deploy a serverless runtime """
    setup_lithops_logger(logging.DEBUG)

    verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, storage=storage, runtime_name=name)
    config = default_config(config_data=config, config_overwrite=config_ow)

    if config['lithops']['mode'] != SERVERLESS:
        raise Exception('"lithops runtime deploy" command is only available for serverless backends')

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, internal_storage)

    runtime_info = compute_handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    runtime_memory = memory or runtime_info['runtime_memory']
    runtime_timeout = timeout or runtime_info['runtime_timeout']

    runtime_key = compute_handler.get_runtime_key(runtime_name, runtime_memory, __version__)
    runtime_meta = compute_handler.deploy_runtime(runtime_name, runtime_memory, runtime_timeout)
    runtime_meta['runtime_timeout'] = runtime_timeout
    internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    logger.info('Runtime deployed')


@runtime.command('list')
@click.argument('name', default='all', required=False)
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_runtimes(name, config, backend, storage, debug):
    """ list all deployed serverless runtime. """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != SERVERLESS:
        raise Exception('"lithops runtime list" command is only available for serverless backends')

    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, None)
    runtimes = compute_handler.list_runtimes(runtime_name=name)

    headers = ['Runtime Name', 'Memory Size', 'Lithops Version', 'Worker Name']

    print()
    print(tabulate(runtimes, headers=headers))
    print(f'\nTotal runtimes: {len(runtimes)}')


@runtime.command('update')
@click.argument('name', required=True)
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def update(name, config, backend, storage, debug):
    """ Update a serverless runtime """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, storage=storage, runtime_name=name)
    config = default_config(config_data=config, config_overwrite=config_ow)

    if config['lithops']['mode'] != SERVERLESS:
        raise Exception('"lithops runtime update" command is only available for serverless backends')

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, internal_storage)

    runtime_info = compute_handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    runtime_timeout = runtime_info['runtime_timeout']

    logger.info(f'Updating runtime: {runtime_name}')

    runtimes = compute_handler.list_runtimes(runtime_name)

    for runtime in runtimes:
        if runtime[2] == __version__:
            runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1], runtime[2])
            runtime_meta = compute_handler.deploy_runtime(runtime[0], runtime[1], runtime_timeout)
            internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    logger.info('Runtime updated')


@runtime.command('delete')
@click.argument('name', required=True)
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--memory', '-m', default=None, help='runtime memory')
@click.option('--version', '-v', default=None, help='lithops version')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def delete(name, config, memory, version, backend, storage, debug):
    """ delete a serverless runtime """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, storage=storage, runtime_name=name)
    config = default_config(config_data=config, config_overwrite=config_ow)

    if config['lithops']['mode'] != SERVERLESS:
        raise Exception('"lithops runtime delete" command is only available for serverless backends')

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)
    compute_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(compute_config, internal_storage)

    runtime_info = compute_handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']

    runtimes = compute_handler.list_runtimes(runtime_name)
    runtimes_to_delete = []

    for runtime in runtimes:
        to_delete = True
        if memory is not None and runtime[1] != int(memory):
            to_delete = False
        if version is not None and runtime[2] != version:
            to_delete = False
        if to_delete:
            runtimes_to_delete.append((runtime[0], runtime[1], runtime[2]))

    if not runtimes_to_delete:
        logger.info("Runtime not found")
        return

    for runtime in runtimes_to_delete:
        compute_handler.delete_runtime(runtime[0], runtime[1], runtime[2])
        runtime_key = compute_handler.get_runtime_key(runtime[0], runtime[1], runtime[2])
        internal_storage.delete_runtime_meta(runtime_key)

    logger.info("Runtime deleted")


# /---------------------------------------------------------------------------/
#
# lithops jobs
#
# /---------------------------------------------------------------------------/

@click.group('job')
@click.pass_context
def job(ctx):
    pass


@job.command('list', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_jobs(config, backend, region, debug):
    """ List Standalone Jobs """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('"lithops job list" command is only available for standalone backends. '
                        f'Please use "lithops job list -b {set(STANDALONE_BACKENDS)}"')

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)

    if not compute_handler.is_initialized():
        logger.info("The backend is not initialized")
        return

    compute_handler.init()

    if not compute_handler.backend.master.is_ready():
        logger.info(f"{compute_handler.backend.master} is stopped")
        return

    if not compute_handler._is_master_service_ready():
        logger.info(f"Lithops service is not running in {compute_handler.backend.master}")
        return

    logger.info(f'Listing jobs submitted to {compute_handler.backend.master}')
    job_list = compute_handler.list_jobs()

    headers = job_list.pop(0)
    key_index = headers.index("Submitted")

    try:
        import pytz
        from tzlocal import get_localzone
        local_tz = get_localzone()

        def convert_utc_to_local(utc_timestamp):
            utc_time = datetime.strptime(utc_timestamp, '%Y-%m-%d %H:%M:%S %Z')
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(local_tz)
            return local_time.strftime('%Y-%m-%d %H:%M:%S %Z')

        for row in job_list:
            row[key_index] = convert_utc_to_local(row[key_index])
    except ModuleNotFoundError:
        pass

    sorted_data = sorted(job_list, key=lambda x: x[key_index])

    print()
    print(tabulate(sorted_data, headers=headers))
    print(f'\nTotal jobs: {len(job_list)}')


# /---------------------------------------------------------------------------/
#
# lithops workers
#
# /---------------------------------------------------------------------------/

@click.group('worker')
@click.pass_context
def worker(ctx):
    pass


@worker.command('list', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_workers(config, backend, region, debug):
    """ List Standalone Jobs """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('"lithops worker list" command is only available for standalone backends. '
                        f'Please use "lithops worker list -b {set(STANDALONE_BACKENDS)}"')

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)

    if not compute_handler.is_initialized():
        logger.info("The backend is not initialized")
        return

    compute_handler.init()

    if not compute_handler.backend.master.is_ready():
        logger.info(f"{compute_handler.backend.master} is stopped")
        return

    if not compute_handler._is_master_service_ready():
        logger.info(f"Lithops service is not running in {compute_handler.backend.master}")
        return

    logger.info(f'Listing available workers in {compute_handler.backend.master}')
    worker_list = compute_handler.list_workers()

    headers = worker_list.pop(0)
    key_index = headers.index("Created")

    try:
        import pytz
        from tzlocal import get_localzone
        local_tz = get_localzone()

        def convert_utc_to_local(utc_timestamp):
            utc_time = datetime.strptime(utc_timestamp, '%Y-%m-%d %H:%M:%S %Z')
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(local_tz)
            return local_time.strftime('%Y-%m-%d %H:%M:%S %Z')

        for row in worker_list:
            row[key_index] = convert_utc_to_local(row[key_index])
    except ModuleNotFoundError:
        pass

    sorted_data = sorted(worker_list, key=lambda x: x[key_index])

    print()
    print(tabulate(sorted_data, headers=headers))
    print(f'\nTotal workers: {len(worker_list)}')


# /---------------------------------------------------------------------------/
#
# lithops image
#
# /---------------------------------------------------------------------------/

@click.group('image')
@click.pass_context
def image(ctx):
    pass


@image.command('build', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument('name', required=False)
@click.option('--file', '-f', default=None, help='file needed to build the image', type=click.Path(exists=True))
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--overwrite', '-o', is_flag=True, help='overwrite the image if it already exists')
@click.option('--include', '-i', multiple=True, help='include source:destination paths', type=str)
@click.pass_context
def build_image(ctx, name, file, config, backend, region, debug, overwrite, include):
    """ build a VM image """
    setup_lithops_logger(logging.DEBUG)

    if name:
        verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('"lithops image build" command is only available for standalone backends. '
                        f'Please use "lithops image build -b {set(STANDALONE_BACKENDS)}"')

    for src_dst_file in include:
        src_file, dst_file = src_dst_file.split(':')
        if not os.path.isfile(src_file):
            raise FileNotFoundError(f"The file '{src_file}' does not exist")

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)
    compute_handler.build_image(name, file, overwrite, include, ctx.args)

    logger.info('VM Image built')


@image.command('delete', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument('name', required=True)
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.pass_context
def delete_image(ctx, name, config, backend, region, debug):
    """ Delete a VM image """
    setup_lithops_logger(logging.DEBUG)

    if name:
        verify_runtime_name(name)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('"lithops image delete" command is only available for standalone backends. '
                        f'Please use "lithops image delete -b {set(STANDALONE_BACKENDS)}"')

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)
    compute_handler.delete_image(name)

    logger.info('VM Image deleted')


@image.command('list', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option('--config', '-c', default=None, help='path to yaml config file', type=click.Path(exists=True))
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_images(config, backend, region, debug):
    """ List VM images """
    log_level = logging.INFO if not debug else logging.DEBUG
    setup_lithops_logger(log_level)

    config = load_yaml_config(config) if config else None
    config_ow = set_config_ow(backend=backend, region=region)
    config = default_config(config_data=config, config_overwrite=config_ow, load_storage_config=False)

    if config['lithops']['mode'] != STANDALONE:
        raise Exception('"lithops image build" command is only available for standalone backends. '
                        f'Please use "lithops image list -b {set(STANDALONE_BACKENDS)}"')

    compute_config = extract_standalone_config(config)
    compute_handler = StandaloneHandler(compute_config)

    logger.info('Listing all Ubuntu Linux 22.04 VM Images')
    vm_images = compute_handler.list_images()

    headers = ['Image Name', 'Image ID', 'Creation Date']

    print()
    print(tabulate(vm_images, headers=headers))
    print(f'\nTotal VM images: {len(vm_images)}')


lithops_cli.add_command(runtime)
lithops_cli.add_command(image)
lithops_cli.add_command(job)
lithops_cli.add_command(worker)
lithops_cli.add_command(logs)
lithops_cli.add_command(storage)

if __name__ == '__main__':
    lithops_cli()
