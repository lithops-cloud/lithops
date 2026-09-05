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
import getpass
import logging
import shutil
import subprocess as sp
from itertools import cycle
from tabulate import tabulate
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

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
    CLEANER_DIR,
    JOBS_DIR,
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


def set_config_ow(
    backend: Optional[str] = None,
    storage: Optional[str] = None,
    runtime_name: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Builds the config overwrite that the global CLI options impose on top of
    whatever the user config file provides
    """
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


def _load_user_config(config_path: Optional[str]) -> Optional[Dict[str, Any]]:
    return load_yaml_config(config_path) if config_path else None


def _setup_cli_logger(debug: bool) -> None:
    setup_lithops_logger(logging.DEBUG if debug else logging.INFO)


def _resolved_config(
    config_path: Optional[str],
    *,
    backend: Optional[str] = None,
    storage: Optional[str] = None,
    runtime_name: Optional[str] = None,
    region: Optional[str] = None,
    load_storage_config: bool = True,
) -> Dict[str, Any]:
    """
    Loads the user config file, if any, and merges the CLI options into it
    """
    config = _load_user_config(config_path)
    config_ow = set_config_ow(
        backend=backend,
        storage=storage,
        runtime_name=runtime_name,
        region=region,
    )
    return default_config(
        config_data=config,
        config_overwrite=config_ow,
        load_storage_config=load_storage_config,
    )


def _require_mode(config: Dict[str, Any], mode: str, command: str) -> None:
    """
    Rejects a command that the configured compute mode cannot serve
    """
    if config['lithops']['mode'] == mode:
        return
    if mode == STANDALONE:
        raise Exception(
            f'{command} is only available for standalone backends. '
            f'Please use "{command} -b {set(STANDALONE_BACKENDS)}"'
        )
    raise Exception(
        f'"{command}" command is only available for serverless backends'
    )


def _standalone_handler(config: Dict[str, Any]) -> StandaloneHandler:
    return StandaloneHandler(extract_standalone_config(config))


def _serverless_handler(
    config: Dict[str, Any], internal_storage: Optional[InternalStorage] = None
) -> ServerlessHandler:
    return ServerlessHandler(
        extract_serverless_config(config), internal_storage
    )


def _compute_handler(
    config: Dict[str, Any], internal_storage: Optional[InternalStorage] = None
):
    """
    Builds the compute handler that matches the configured compute mode
    """
    mode = config['lithops']['mode']
    if mode == LOCALHOST:
        return LocalhostHandler(extract_localhost_config(config))
    if mode == SERVERLESS:
        return _serverless_handler(config, internal_storage)
    if mode == STANDALONE:
        return _standalone_handler(config)
    raise Exception(f'Unknown compute mode: {mode}')


def _prepare_serverless(
    name: Optional[str],
    config_path: Optional[str],
    backend: Optional[str],
    storage: Optional[str],
    debug: bool,
    command: str,
    *,
    always_debug: bool = False,
    load_storage: bool = True,
) -> Tuple[ServerlessHandler, Optional[InternalStorage]]:
    """
    Common setup of the serverless commands: logging, runtime name checks,
    config resolution and the handler the command then drives
    """
    _setup_cli_logger(debug or always_debug)
    if name:
        verify_runtime_name(name)
    config = _resolved_config(
        config_path,
        backend=backend,
        storage=storage,
        runtime_name=name,
        load_storage_config=load_storage,
    )
    _require_mode(config, SERVERLESS, command)
    internal_storage = (
        InternalStorage(extract_storage_config(config)) if load_storage else None
    )
    return _serverless_handler(config, internal_storage), internal_storage


def _prepare_standalone(
    config_path: Optional[str],
    backend: Optional[str],
    region: Optional[str],
    debug: bool,
    command: str,
    *,
    always_debug: bool = False,
) -> StandaloneHandler:
    """
    Common setup of the standalone commands. Standalone never needs the
    object storage, so it is not loaded
    """
    _setup_cli_logger(debug or always_debug)
    config = _resolved_config(
        config_path,
        backend=backend,
        region=region,
        load_storage_config=False,
    )
    _require_mode(config, STANDALONE, command)
    return _standalone_handler(config)


def _standalone_service_ready(handler: StandaloneHandler) -> bool:
    """
    Tells whether the master VM is up and serving, logging why it is not
    """
    if not handler.is_initialized():
        logger.info("The backend is not initialized")
        return False
    handler.init()
    if not handler.backend.master.is_ready():
        logger.info(f"{handler.backend.master} is stopped")
        return False
    if not handler._is_master_service_ready():
        logger.info(
            f"Lithops service is not running in {handler.backend.master}"
        )
        return False
    return True


def _utc_to_local(utc_timestamp: str, local_tz) -> str:
    import pytz
    utc_time = datetime.strptime(utc_timestamp, '%Y-%m-%d %H:%M:%S %Z')
    utc_time = utc_time.replace(tzinfo=pytz.utc)
    local_time = utc_time.astimezone(local_tz)
    return local_time.strftime('%Y-%m-%d %H:%M:%S %Z')


def _localize_and_sort_rows(rows: List[List], key_index: int) -> List[List]:
    """
    Sorts the rows by their timestamp column, rewritten to the local time
    zone. pytz and tzlocal are optional, so without them times stay in UTC
    """
    try:
        from tzlocal import get_localzone
        local_tz = get_localzone()
        for row in rows:
            row[key_index] = _utc_to_local(row[key_index], local_tz)
    except ModuleNotFoundError:
        pass
    return sorted(rows, key=lambda row: row[key_index])


def _print_table(
    rows: List, headers: Union[str, List[str]], total_label: str
) -> None:
    print()
    print(tabulate(rows, headers=headers))
    print(f'\nTotal {total_label}: {len(rows)}')


def _format_storage_objects(objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keeps only the object attributes the storage list command shows, in a
    display-friendly form
    """
    formatted = []
    for obj in objects:
        row = {}
        if 'Key' in obj:
            row['Key'] = obj['Key']
        if 'LastModified' in obj:
            row['LastModified'] = obj['LastModified'].strftime(
                "%b %d %Y %H:%M:%S"
            )
        if 'Size' in obj:
            row['Size'] = sizeof_fmt(obj['Size'])
        formatted.append(row)
    return formatted


def _run_with_spinner(message: str, func: Callable) -> None:
    """
    Runs a blocking call on a worker thread while animating a spinner, then
    re-raises whatever the call raised
    """
    with ThreadPoolExecutor() as ex:
        future = ex.submit(func)
        spinner = cycle(r"-\|/")
        while not future.done():
            print(f"{message} {next(spinner)}", end="\r")
            time.sleep(0.1)
        future.result()


def _make_storage(
    config_path: Optional[str], backend: Optional[str], debug: bool
) -> Storage:
    _setup_cli_logger(debug)
    return Storage(config=_load_user_config(config_path), backend=backend)


def _follow_log(fileobj) -> Iterator[str]:
    """
    Yields complete lines as they are appended to the log, tail -f style,
    and stops once the log file is gone
    """
    line = ''
    while True:
        if not os.path.isfile(FN_LOG_FILE):
            break
        tmp = fileobj.readline()
        if tmp:
            line += tmp
            if line.endswith("\n"):
                yield line
                line = ''
        else:
            time.sleep(1)


def _clean_local_temp_data() -> None:
    """
    Deletes the local temporary data of this machine: logs, cached modules,
    custom runtimes and localhost job data.

    Only the contents go, never the directory skeleton that lithops/config.py
    creates on import: a Lithops process that is already running would never
    see those directories come back, and would die writing its next log line.
    CLEANER_DIR is skipped altogether, since it holds the pending cleaner
    requests of every process on this machine plus the lock of the running
    cleaner, and dropping a request would leak the data it asks to delete.
    Anything else a parallel job is using does go, which is intended: this
    command is explicitly destructive.
    """
    try:
        entries = list(os.scandir(LITHOPS_TEMP_DIR))
    except FileNotFoundError:
        entries = []

    for entry in entries:
        if entry.path == CLEANER_DIR:
            continue
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path, ignore_errors=True)
        else:
            try:
                os.remove(entry.path)
            except OSError:
                pass

    for temp_dir in (LITHOPS_TEMP_DIR, JOBS_DIR, LOGS_DIR, CLEANER_DIR):
        os.makedirs(temp_dir, exist_ok=True)


@click.group('lithops_cli')
@click.version_option()
def lithops_cli():
    pass


@lithops_cli.command('clean')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option(
    '--all', '-a', 'delete_all', is_flag=True,
    help='delete all, including master VM in case of standalone'
)
def clean(config, backend, storage, debug, region, delete_all):
    _setup_cli_logger(debug)
    logger.info('Cleaning all Lithops information')

    cfg = _resolved_config(
        config, backend=backend, storage=storage, region=region
    )
    compute_backend = cfg['lithops']['backend']
    internal_storage = InternalStorage(extract_storage_config(cfg))
    compute_handler = _compute_handler(cfg, internal_storage)
    compute_handler.clean(all=delete_all)

    obj_storage = internal_storage.storage
    runtimes_path = f'{RUNTIMES_PREFIX}/{compute_backend}'
    clean_bucket(obj_storage, obj_storage.bucket, runtimes_path, sleep=1)
    clean_bucket(obj_storage, obj_storage.bucket, JOBS_PREFIX, sleep=1)

    _clean_local_temp_data()
    shutil.rmtree(
        os.path.join(CACHE_DIR, RUNTIMES_PREFIX, compute_backend),
        ignore_errors=True,
    )
    logger.info('All Lithops temporary data cleaned')


@lithops_cli.command('test')
@click.option(
    '--config', '-c', default=None,
    help='Path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='Compute backend')
@click.option('--storage', '-s', default=None, help='Storage backend')
@click.option('--debug', '-d', is_flag=True, help='Debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option(
    '--test', '-t', default=None,
    help=(
        'Run a specific test. To avoid running similarly named tests '
        'you may prefix the tester with its test class, '
        'e.g. TestAsync::test_call_async '
        'Type "-t help" for the complete tests list'
    )
)
@click.option(
    '--exitfirst', '-x', is_flag=True,
    help='Stops test run upon first occurrence of a failed test'
)
def test(test, config, backend, storage, debug, region, exitfirst):
    import pytest

    dir_path = os.path.dirname(os.path.realpath(__file__))
    tests_path = os.path.abspath(os.path.join(dir_path, '..', 'tests'))

    if test == 'help':
        pytest.main([tests_path, "--collect-only"])
        return

    cmd = [tests_path, "-v"]
    if exitfirst:
        cmd.append("-x")
    if debug:
        cmd.extend(["-o", "log_cli=true", "--log-cli-level=DEBUG"])
    for option, value in (
        ("--config", config),
        ("--backend", backend),
        ("--storage", storage),
        ("--region", region),
        ("-k", test),
    ):
        if value:
            cmd.extend([option, value])

    print(f"Executing lithops tests: pytest {' '.join(cmd[1:])}")
    pytest.main(cmd)


@lithops_cli.command('hello')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option(
    '--map', 'map_count', '-m', default=None, type=click.IntRange(min=1),
    help='number of map invocations to run instead of a single call_async'
)
def hello(config, backend, storage, debug, region, map_count):
    _setup_cli_logger(debug)
    config_data = _load_user_config(config)

    try:
        username = getpass.getuser()
    except (OSError, KeyError):
        # No login name and no matching passwd entry, which happens in some
        # containers
        username = 'World'

    def hello_fn(name):
        return f'Hello {name}!'

    expected = f'Hello {username}!'
    with lithops.FunctionExecutor(
        config=config_data, backend=backend, storage=storage, region=region
    ) as fexec:
        if map_count:
            fexec.map(hello_fn, [username] * map_count)
            results = fexec.get_result()
            succeeded = all(result == expected for result in results)
            message = (
                f'All {map_count} map activations returned: {expected}\n'
                'Lithops is working as expected :)'
                if succeeded else
                f'{results} Something went wrong :('
            )
        else:
            fexec.call_async(hello_fn, username)
            result = fexec.get_result()
            message = (
                f'{result} Lithops is working as expected :)'
                if result == expected else
                f'{result} Something went wrong :('
            )

    print()
    print(message)
    print()


@lithops_cli.command('attach')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option("--start", is_flag=True, default=False, help="Start the master VM if needed.")
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option('--region', '-r', default=None, help='compute backend region')
def attach(config, backend, start, debug, region):
    """Create or attach to a SSH session on Lithops master VM"""
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops attach'
    )

    if not handler.is_initialized():
        logger.info("The backend is not initialized")
        return
    handler.init()
    if not start and not handler.backend.master.is_ready():
        logger.info(f"{handler.backend.master} is stopped")
        return

    if start:
        handler.backend.master.start()

    master_ip = handler.backend.master.get_public_ip()
    user = handler.backend.master.ssh_credentials['username']
    key_file = (
        handler.backend.master.ssh_credentials['key_filename']
        or '~/.ssh/id_rsa'
    )
    key_file = os.path.abspath(os.path.expanduser(key_file))

    if not os.path.exists(key_file):
        raise Exception(f'Private key file {key_file} does not exist')

    print(f'Got master VM public IP address: {master_ip}')
    print(f'Loading ssh private key from: {key_file}')
    print('Creating SSH Connection to lithops master VM')
    cmd = [
        'ssh',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'StrictHostKeyChecking=no',
        '-i', key_file,
        f'{user}@{master_ip}',
    ]

    handler.backend.master.wait_ready()
    sp.run(cmd)


# /---------------------------------------------------------------------------/
#
# lithops storage
#
# /---------------------------------------------------------------------------/

@click.group('storage')
def storage():
    pass


@storage.command('put')
@click.argument('filename', type=click.Path(exists=True))
@click.argument('bucket')
@click.option('--key', '-k', default=None, help='object key')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
def upload_file(filename, bucket, key, backend, debug, config):
    client = _make_storage(config, backend, debug)
    dest_key = key or filename

    def _upload():
        logger.info(
            f'Uploading file {filename} to '
            f'{client.backend}://{bucket}/{dest_key}'
        )
        if client.upload_file(filename, bucket, key):
            file_size = os.path.getsize(filename)
            logger.info(
                f'Upload File {filename} - Size: {sizeof_fmt(file_size)} - Ok'
            )
        else:
            logger.error(f'Upload File {filename} - Error')

    _run_with_spinner("Uploading file", _upload)


@storage.command('get')
@click.argument('bucket')
@click.argument('key')
@click.option('--out', '-o', default=None, help='output filename')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
def download_file(bucket, key, out, backend, debug, config):
    client = _make_storage(config, backend, debug)
    dest = out or key

    def _download():
        logger.info(
            f'Downloading file {client.backend}://{bucket}/{key} to {dest}'
        )
        if client.download_file(bucket, key, out):
            file_size = os.path.getsize(dest)
            logger.info(
                f'Download File {key} - Size: {sizeof_fmt(file_size)} - Ok'
            )
        else:
            logger.error(f'Download File {key} - Error')

    _run_with_spinner("Downloading file", _download)


@storage.command('delete')
@click.argument('bucket')
@click.argument('key', required=False)
@click.option('--prefix', '-p', default=None, help='key prefix')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
def delete_object(bucket, key, prefix, backend, debug, config):
    client = _make_storage(config, backend, debug)

    if key:
        logger.info(f'Deleting object "{key}" from bucket "{bucket}"')
        client.delete_object(bucket, key)
        logger.info('Object deleted successfully')
        return

    if prefix:
        objs = client.list_keys(bucket, prefix)
        logger.info(
            f'Deleting {len(objs)} objects with prefix "{prefix}" '
            f'from bucket "{bucket}"'
        )
        client.delete_objects(bucket, objs)
        logger.info('Objects deleted successfully')
        return

    raise click.UsageError('Provide KEY or --prefix')


@storage.command('list')
@click.argument('bucket')
@click.option('--prefix', '-p', default=None, help='key prefix')
@click.option('--backend', '-b', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
def list_bucket(prefix, bucket, backend, debug, config):
    client = _make_storage(config, backend, debug)
    logger.info(f'Listing objects in bucket {bucket}')
    objs = _format_storage_objects(client.list_objects(bucket, prefix=prefix))

    if objs:
        _print_table(objs, headers="keys", total_label='objects')
    else:
        print(
            f'\nNo information can be listed from bucket "{bucket}" '
            f'using current "{client.backend}" backend'
        )


# /---------------------------------------------------------------------------/
#
# lithops logs
#
# /---------------------------------------------------------------------------/

@click.group('logs')
def logs():
    pass


@logs.command('poll')
def poll():
    logging.basicConfig(level=logging.DEBUG)

    while True:
        if os.path.isfile(FN_LOG_FILE):
            with open(FN_LOG_FILE, 'r') as log_file:
                for line in _follow_log(log_file):
                    print(line, end='')
        else:
            time.sleep(1)


@logs.command('get')
@click.argument('job_key')
def get_logs(job_key):
    log_file = os.path.join(LOGS_DIR, f'{job_key}.log')

    if not os.path.isfile(log_file):
        print(f'The execution id: {job_key} does not exist in logs')
        return

    with open(log_file, 'r') as content_file:
        print(content_file.read())


# /---------------------------------------------------------------------------/
#
# lithops runtime
#
# /---------------------------------------------------------------------------/

@click.group('runtime')
def runtime():
    pass


@runtime.command(
    'build',
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True)
)
@click.argument('name', required=False)
@click.option(
    '--file', '-f', default=None,
    help='file needed to build the runtime', type=click.Path(exists=True)
)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.pass_context
def build(ctx, name, file, config, backend, debug):
    """ build a serverless runtime. """
    handler, _ = _prepare_serverless(
        name, config, backend, None, debug,
        'lithops runtime build',
        always_debug=True,
        load_storage=False,
    )
    runtime_info = handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    handler.build_runtime(runtime_name, file, ctx.args)
    logger.info('Runtime built')


@runtime.command('deploy')
@click.argument('name', required=True)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
@click.option('--timeout', default=None, help='runtime timeout', type=int)
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def deploy(name, storage, backend, memory, timeout, config, debug):
    """ deploy a serverless runtime """
    handler, internal_storage = _prepare_serverless(
        name, config, backend, storage, debug,
        'lithops runtime deploy',
        always_debug=True,
    )
    runtime_info = handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    runtime_memory = memory or runtime_info['runtime_memory']
    runtime_timeout = timeout or runtime_info['runtime_timeout']

    runtime_key = handler.get_runtime_key(
        runtime_name, runtime_memory, __version__
    )
    runtime_meta = handler.deploy_runtime(
        runtime_name, runtime_memory, runtime_timeout
    )
    runtime_meta['runtime_timeout'] = runtime_timeout
    internal_storage.put_runtime_meta(runtime_key, runtime_meta)
    logger.info('Runtime deployed')


@runtime.command('list')
@click.argument('name', default='all', required=False)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_runtimes(name, config, backend, storage, debug):
    """ list all deployed serverless runtime. """
    handler, _ = _prepare_serverless(
        None, config, backend, storage, debug,
        'lithops runtime list',
        load_storage=False,
    )
    runtimes = handler.list_runtimes(runtime_name=name)
    headers = ['Runtime Name', 'Memory Size', 'Lithops Version', 'Worker Name']
    _print_table(runtimes, headers, 'runtimes')


@runtime.command('update')
@click.argument('name', required=True)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def update(name, config, backend, storage, debug):
    """ Update a serverless runtime """
    handler, internal_storage = _prepare_serverless(
        name, config, backend, storage, debug, 'lithops runtime update'
    )
    runtime_info = handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']
    runtime_timeout = runtime_info['runtime_timeout']

    logger.info(f'Updating runtime: {runtime_name}')

    # Rows are (name, memory, version, worker name), see list_runtimes
    for rt in handler.list_runtimes(runtime_name):
        if rt[2] != __version__:
            continue
        runtime_key = handler.get_runtime_key(rt[0], rt[1], rt[2])
        runtime_meta = handler.deploy_runtime(rt[0], rt[1], runtime_timeout)
        internal_storage.put_runtime_meta(runtime_key, runtime_meta)

    logger.info('Runtime updated')


@runtime.command('delete')
@click.argument('name', required=True)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--memory', '-m', default=None, help='runtime memory')
@click.option('--version', '-v', default=None, help='lithops version')
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--storage', '-s', default=None, help='storage backend')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def delete(name, config, memory, version, backend, storage, debug):
    """ delete a serverless runtime """
    handler, internal_storage = _prepare_serverless(
        name, config, backend, storage, debug, 'lithops runtime delete'
    )
    runtime_info = handler.get_runtime_info()
    runtime_name = runtime_info['runtime_name']

    # Rows are (name, memory, version, worker name), see list_runtimes
    runtimes_to_delete = [
        (rt[0], rt[1], rt[2])
        for rt in handler.list_runtimes(runtime_name)
        if (memory is None or rt[1] == int(memory))
        and (version is None or rt[2] == version)
    ]

    if not runtimes_to_delete:
        logger.info("Runtime not found")
        return

    for rt_name, rt_memory, rt_version in runtimes_to_delete:
        handler.delete_runtime(rt_name, rt_memory, rt_version)
        runtime_key = handler.get_runtime_key(rt_name, rt_memory, rt_version)
        internal_storage.delete_runtime_meta(runtime_key)

    logger.info("Runtime deleted")


# /---------------------------------------------------------------------------/
#
# lithops jobs
#
# /---------------------------------------------------------------------------/

@click.group('job')
def job():
    pass


@job.command('list')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_jobs(config, backend, region, debug):
    """ List Standalone Jobs """
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops job list'
    )
    if not _standalone_service_ready(handler):
        return

    logger.info(f'Listing jobs submitted to {handler.backend.master}')
    job_list = handler.list_jobs()
    if not job_list:
        _print_table([], [], 'jobs')
        return

    headers = job_list.pop(0)
    key_index = headers.index("Submitted")
    rows = _localize_and_sort_rows(job_list, key_index)
    _print_table(rows, headers, 'jobs')


# /---------------------------------------------------------------------------/
#
# lithops workers
#
# /---------------------------------------------------------------------------/

@click.group('worker')
def worker():
    pass


@worker.command('list')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_workers(config, backend, region, debug):
    """ List Standalone Workers """
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops worker list'
    )
    if not _standalone_service_ready(handler):
        return

    logger.info(f'Listing available workers in {handler.backend.master}')
    worker_list = handler.list_workers()
    if not worker_list:
        _print_table([], [], 'workers')
        return

    headers = worker_list.pop(0)
    key_index = headers.index("Created")
    rows = _localize_and_sort_rows(worker_list, key_index)
    _print_table(rows, headers, 'workers')


# /---------------------------------------------------------------------------/
#
# lithops image
#
# /---------------------------------------------------------------------------/

@click.group('image')
def image():
    pass


@image.command(
    'build',
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True)
)
@click.argument('name', required=False)
@click.option(
    '--file', '-f', default=None,
    help='file needed to build the image', type=click.Path(exists=True)
)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
@click.option(
    '--overwrite', '-o', is_flag=True,
    help='overwrite the image if it already exists'
)
@click.option(
    '--include', '-i', multiple=True,
    help='include source:destination paths', type=str
)
@click.pass_context
def build_image(ctx, name, file, config, backend, region, debug, overwrite, include):
    """ build a VM image """
    if name:
        verify_runtime_name(name)
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops image build',
        always_debug=True,
    )

    for src_dst_file in include:
        src_file, dst_file = src_dst_file.split(':')
        if not os.path.isfile(src_file):
            raise FileNotFoundError(f"The file '{src_file}' does not exist")

    handler.build_image(name, file, overwrite, include, ctx.args)
    logger.info('VM Image built')


@image.command('delete')
@click.argument('name', required=True)
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def delete_image(name, config, backend, region, debug):
    """ Delete a VM image """
    if name:
        verify_runtime_name(name)
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops image delete',
        always_debug=True,
    )
    handler.delete_image(name)
    logger.info('VM Image deleted')


@image.command('list')
@click.option(
    '--config', '-c', default=None,
    help='path to yaml config file', type=click.Path(exists=True)
)
@click.option('--backend', '-b', default=None, help='compute backend')
@click.option('--region', '-r', default=None, help='compute backend region')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def list_images(config, backend, region, debug):
    """ List VM images """
    handler = _prepare_standalone(
        config, backend, region, debug, 'lithops image list'
    )
    logger.info('Listing all Ubuntu VM images')
    vm_images = handler.list_images()
    headers = ['Image Name', 'Image ID', 'Creation Date']
    _print_table(vm_images, headers, 'VM images')


lithops_cli.add_command(runtime)
lithops_cli.add_command(image)
lithops_cli.add_command(job)
lithops_cli.add_command(worker)
lithops_cli.add_command(logs)
lithops_cli.add_command(storage)

if __name__ == '__main__':
    lithops_cli()
