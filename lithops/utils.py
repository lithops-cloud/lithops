#
# Copyright 2018 PyWren Team
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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

import re
import os
import sys
import uuid
import json
import socket
import shutil
import base64
import inspect
import struct
import lithops
import zipfile
import platform
import threading
import logging.config
import subprocess as sp
from enum import Enum
from contextlib import closing

from typing import List

from lithops import constants
from lithops.version import __version__


logger = logging.getLogger(__name__)


class ShutdownSafeStreamHandler(logging.StreamHandler):
    """StreamHandler that does not traceback when the stream is already closed."""

    def emit(self, record):
        try:
            stream = self.stream
            if stream is None or getattr(stream, 'closed', False):
                return
            msg = self.format(record)
            stream.write(msg + self.terminator)
            self.flush()
        except RecursionError:
            # handleError() logs, so it would recurse again. Same as logging
            raise
        except (ValueError, OSError):
            # The stream was closed between the check above and the write
            return
        except Exception:
            self.handleError(record)


def uuid_str():
    return str(uuid.uuid4())


def _as_future_list(fs):
    """Wrap a single future; leave list / FuturesList unchanged."""
    return fs if isinstance(fs, list) else [fs]


def _future_id(fut):
    return (fut.executor_id, fut.job_id, fut.call_id)


def create_executor_id(lenght=6):
    """
    Creates the ID of a new executor. Executors of the same session share the
    session ID and are told apart by a counter, both kept in the environment
    so that they survive across processes
    """
    if '__LITHOPS_SESSION_ID' in os.environ:
        session_id = os.environ['__LITHOPS_SESSION_ID']
    else:
        session_id = uuid_str().replace('/', '')[:lenght]
        os.environ['__LITHOPS_SESSION_ID'] = session_id

    if '__LITHOPS_TOTAL_EXECUTORS' in os.environ:
        exec_num = int(os.environ['__LITHOPS_TOTAL_EXECUTORS']) + 1
    else:
        exec_num = 0
    os.environ['__LITHOPS_TOTAL_EXECUTORS'] = str(exec_num)

    return f'{session_id}-{exec_num}'


# Carries the monitoring queues of an executor down to the workers, so that an
# executor created inside one of them can extend the chain
MONITORING_QUEUES_ENV = '__LITHOPS_MONITORING_QUEUES'


def monitoring_queue_name(executor_id: str) -> str:
    """Returns the name of the queue an executor is monitored through"""
    return f'lithops-{executor_id}'


def remote_invoker_queue_name(executor_id: str) -> str:
    """
    Returns the name of the queue the remote invoker is monitored through.

    It follows the calls of an executor it does not own, so it cannot read
    the queue of that executor: a message taken from a queue is gone, and
    the client waiting on the other end would never see it
    """
    return f'{monitoring_queue_name(executor_id)}-invoker'


def monitoring_queues(executor_id: str) -> List[str]:
    """
    Returns every queue a call status of this executor has to be published to:
    the queue of each executor up the chain, ending with this one.

    The chain travels in the environment instead of being read back out of the
    executor id, because the id does not say how deep it is: a worker adds the
    job and the call to the session id while a remote invoker adds only the
    job, so the same number of tokens can stand for different chains
    """
    parent_queues = []
    raw_queues = os.environ.get(MONITORING_QUEUES_ENV)
    if raw_queues:
        try:
            parent_queues = list(json.loads(raw_queues))
        except ValueError:
            logger.warning(
                f'Ignoring a malformed {MONITORING_QUEUES_ENV}: {raw_queues}'
            )

    queue = monitoring_queue_name(executor_id)
    if queue in parent_queues:
        # The remote invoker builds the payload of the job it spawns from
        # inside a worker that already exported this very chain, so without
        # this every remotely invoked task would report twice to the client
        return parent_queues
    return parent_queues + [queue]


def get_executor_id():
    """Returns the ID of the last executor created in this session"""
    session_id = os.environ['__LITHOPS_SESSION_ID']
    exec_num = os.environ['__LITHOPS_TOTAL_EXECUTORS']
    return f'{session_id}-{exec_num}'


def iterchunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def agg_data(data_strs):
    """
    Concatenates the data of every call of a job into a single byte string,
    and returns it along with the byte range that each call occupies
    """
    ranges = []
    pos = 0
    for datum in data_strs:
        datum_len = len(datum)
        ranges.append((pos, pos + datum_len - 1))
        pos += datum_len
    return b"".join(data_strs), ranges


def create_futures_list(futures, executor):
    """Creates a new FuturesList bound to the executor that produced it"""
    fl = FuturesList(futures)
    fl.config = executor.config
    fl.executor = executor

    return fl


class FuturesList(list):
    """
    List of futures that can be mapped over again, so that jobs can be
    chained. Chaining replaces the contents with the futures of the new job,
    while alt_list keeps every future of the chain for wait() and get_result()
    """

    # Defaults for lists that were not built by create_futures_list, and for
    # the ones rehydrated by __reduce__, which drops the executor
    executor = None
    config = None

    def _create_executor(self):
        if not self.executor:
            from lithops import FunctionExecutor
            self.executor = FunctionExecutor(config=self.config)

    def _all_futures(self):
        return self.alt_list if hasattr(self, 'alt_list') else self

    def _extend_futures(self, fs):
        # Only the last job of the chain produces the output of the chain
        for fut in self:
            fut._produce_output = False
        if not hasattr(self, 'alt_list'):
            self.alt_list = []
            self.alt_list.extend(self)
        self.alt_list.extend(fs)
        self.clear()
        self.extend(fs)

    def map(self, map_function, sync=False, **kwargs):
        """
        Chains a new map job that takes the results of this one as its input.
        The intermediate results are read by the workers of the new job and
        are never downloaded to the client.

        :param map_function: The function to map over the results
        :param sync: Wait for this job before invoking the new one. Left
            False, the new job is invoked right away and each of its workers
            blocks until its own input is ready, which is worker time you pay
            for. Waiting costs about the same wall-clock time and no idle
            workers, at the price of not overlapping the two invocations
        :param kwargs: Passed on to
            :meth:`~lithops.executors.FunctionExecutor.map`. ``extra_args`` is
            not among them: a chained function is called with the result of
            the previous one and nothing else

        :return: This list, now holding the futures of the new job
        """
        self._create_executor()
        if sync:
            self.executor.wait(self)
        fs = self.executor.map(map_function, self, **kwargs)
        self._extend_futures(fs)
        return self

    def map_reduce(self, map_function, reduce_function, sync=False, **kwargs):
        """
        Chains a new map-reduce job that takes the results of this one as the
        input of its map stage.

        :param map_function: The function to map over the results
        :param reduce_function: The function to reduce the map results with
        :param sync: Wait for this job before invoking the new one. See
            :meth:`map`
        :param kwargs: Passed on to
            :meth:`~lithops.executors.FunctionExecutor.map_reduce`

        :return: This list, now holding the futures of the new job
        """
        self._create_executor()
        if sync:
            self.executor.wait(self)
        fs = self.executor.map_reduce(
            map_function, self, reduce_function, **kwargs
        )
        self._extend_futures(fs)
        return self

    def wait(self, **kwargs):
        """
        Waits for every job of the chain, not only for the last one.

        :param kwargs: Passed on to
            :meth:`~lithops.executors.FunctionExecutor.wait`

        :return: `(fs_done, fs_notdone)`
        """
        self._create_executor()
        return self.executor.wait(self._all_futures(), **kwargs)

    def get_result(self, **kwargs):
        """
        Returns the results of the last job of the chain. The intermediate
        ones are read by the workers, never by the client.

        :param kwargs: Passed on to
            :meth:`~lithops.executors.FunctionExecutor.get_result`

        :return: The results of the last job
        """
        self._create_executor()
        return self.executor.get_result(self._all_futures(), **kwargs)

    def __reduce__(self):
        # The executor is not picklable, and a rehydrated list creates its
        # own. Dropped from the pickled state rather than from the object,
        # so that pickling a list does not detach the one being pickled
        reduced = list(super().__reduce__())
        # A list that never had an attribute set reduces without a state
        state = reduced[2] if len(reduced) > 2 else None
        if isinstance(state, dict) and 'executor' in state:
            state = dict(state)
            state.pop('executor')
            reduced[2] = state
        return tuple(reduced)


_MODE_TO_DEFAULT_BACKEND = {
    constants.LOCALHOST: constants.LOCALHOST,
    constants.SERVERLESS: constants.SERVERLESS_BACKEND_DEFAULT,
    constants.STANDALONE: constants.STANDALONE_BACKEND_DEFAULT,
}


def get_default_backend(mode):
    """Returns the compute backend an execution mode defaults to"""
    if mode in _MODE_TO_DEFAULT_BACKEND:
        return _MODE_TO_DEFAULT_BACKEND[mode]
    if mode:
        raise Exception(f"Unknown execution mode: {mode}")


def get_mode(backend):
    """Returns the execution mode a compute backend belongs to"""
    if backend is None:
        return constants.MODE_DEFAULT
    if backend == constants.LOCALHOST:
        return constants.LOCALHOST
    if backend in constants.SERVERLESS_BACKENDS:
        return constants.SERVERLESS
    if backend in constants.STANDALONE_BACKENDS:
        return constants.STANDALONE
    if backend:
        raise Exception(f"Unknown compute backend: {backend}")


def log_prefix(executor_id, job_id=None, call_id=None) -> str:
    """Identity prefix used in Lithops log messages"""
    parts = [f'ExecutorID {executor_id}']
    if job_id is not None:
        parts.append(f'JobID {job_id}')
    if call_id is not None:
        parts.append(f'CallID {call_id}')
    return ' | '.join(parts)


def setup_lithops_logger(log_level=constants.LOGGER_LEVEL,
                         log_format=constants.LOGGER_FORMAT,
                         stream=None, filename=None):
    """
    Configures the lithops logger. A log level of None, or 'none', leaves the
    logging of the process untouched
    """
    if log_level is None or str(log_level).lower() == 'none':
        return

    if stream is None:
        stream = constants.LOGGER_STREAM

    # Both handlers are always declared, so the unused FileHandler is pointed
    # at os.devnull rather than at a file nobody asked for
    log_to_file = filename is not None
    if filename is None:
        filename = os.devnull

    if isinstance(log_level, str):
        log_level = logging.getLevelName(log_level.upper())

    config_dict = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': log_format
            },
        },
        'handlers': {
            'console_handler': {
                'level': log_level,
                'formatter': 'standard',
                'class': 'lithops.utils.ShutdownSafeStreamHandler',
                'stream': stream
            },
            'file_handler': {
                'level': log_level,
                'formatter': 'standard',
                'class': 'logging.FileHandler',
                'filename': filename,
                'mode': 'a',
            },
        },
        'loggers': {
            'lithops': {
                'handlers': ['console_handler'],
                'level': log_level,
                'propagate': False
            },
        }
    }

    if log_to_file:
        config_dict['loggers']['lithops']['handlers'] = ['file_handler']

    logging.config.dictConfig(config_dict)


_SKIP_HANDLER_ZIP_DIRS = frozenset({'__pycache__', '.pytest_cache'})


def _skip_in_handler_zip(path: str, dst_zip_location: str) -> bool:
    # The zip is often written inside the package directory that is being
    # zipped, so it must not add itself, nor any other package left there
    return os.path.abspath(path) == dst_zip_location or path.endswith('.zip')


def _add_folder_to_handler_zip(
    zip_file: zipfile.ZipFile,
    full_dir_path: str,
    dst_zip_location: str,
    sub_dir: str = ''
) -> None:
    """Adds a directory tree to the zip, under the lithops/ prefix"""
    for name in os.listdir(full_dir_path):
        full_path = os.path.join(full_dir_path, name)
        if os.path.isdir(full_path):
            if name not in _SKIP_HANDLER_ZIP_DIRS:
                _add_folder_to_handler_zip(
                    zip_file,
                    full_path,
                    dst_zip_location,
                    os.path.join(sub_dir, name),
                )
        elif os.path.isfile(full_path):
            if not _skip_in_handler_zip(full_path, dst_zip_location):
                zip_file.write(
                    full_path, os.path.join('lithops', sub_dir, name)
                )


def create_handler_zip(
    dst_zip_location, entry_point_files, entry_point_name=None
):
    """
    Creates the zip package that is uploaded as a function: the entry points
    at its root, and the whole lithops package under lithops/
    """
    dst_zip_location = os.path.abspath(dst_zip_location)
    logger.debug(f"Creating function handler zip in {dst_zip_location}")

    if not isinstance(entry_point_files, list):
        entry_point_files = [entry_point_files]

    created = False
    try:
        with zipfile.ZipFile(
            dst_zip_location, 'w', zipfile.ZIP_DEFLATED
        ) as lithops_zip:
            module_location = os.path.dirname(
                os.path.abspath(lithops.__file__)
            )
            for ep_file in entry_point_files:
                ep_name = entry_point_name or os.path.basename(ep_file)
                lithops_zip.write(ep_file, ep_name)
            _add_folder_to_handler_zip(
                lithops_zip, module_location, dst_zip_location
            )
        created = True
        zip_size = os.path.getsize(dst_zip_location)
        logger.debug(
            f'Function handler zip created - Size: {sizeof_fmt(zip_size)}'
        )
    except Exception as e:
        raise Exception(
            f'Unable to create the {dst_zip_location} package: {e}'
        ) from e
    finally:
        # A half written zip would be uploaded and fail at invocation time
        if not created and os.path.exists(dst_zip_location):
            os.remove(dst_zip_location)


def verify_runtime_name(runtime_name: str) -> None:
    """Asserts that the runtime name can be used as a container image name"""
    assert re.match("^[A-Za-z0-9_/.:-]*$", runtime_name), \
        f'Runtime name "{runtime_name}" not valid'


def timeout_handler(error_msg, signum, frame):
    """Signal handler that turns an alarm into a TimeoutError"""
    raise TimeoutError(error_msg)


def version_str(version_info) -> str:
    """Formats a sys.version_info tuple as major.minor"""
    return f"{version_info[0]}.{version_info[1]}"


def is_unix_system() -> bool:
    """Checks if the current OS is UNIX"""
    return platform.system() != 'Windows'


def is_linux_system() -> bool:
    """Checks if the current OS is LINUX"""
    return platform.system().lower() == "linux"


def is_lithops_worker() -> bool:
    """Checks if the current execution is within a lithops worker"""
    return 'LITHOPS_WORKER' in os.environ


def is_object_processing_function(map_function) -> bool:
    """
    Checks if a function contains the obj parameter, which means
    the user wants to activate the data processing logic
    """
    func_sig = inspect.signature(map_function)
    return 'obj' in func_sig.parameters


def is_notebook() -> bool:
    """Checks if the current execution is within a Jupyter notebook"""
    try:
        return get_ipython().__class__.__name__ == 'ZMQInteractiveShell'
    except NameError:
        return False


def convert_bools_to_string(extra_env):
    """Converts every boolean value of a dictionary to a string, in place"""
    for key, value in extra_env.items():
        if isinstance(value, bool):
            extra_env[key] = str(value)

    return extra_env


def sizeof_fmt(num, suffix='B') -> str:
    """Formats a number of bytes with a binary unit prefix"""
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f'{num:3.1f}{unit}{suffix}'
        num /= 1024.0
    return f'{num:.1f}Yi{suffix}'


def sdb_to_dict(item):
    attr = item['Attributes']
    return {c['Name']: c['Value'] for c in attr}


def dict_to_b64str(the_dict):
    bytes_dict = json.dumps(the_dict, default=str).encode()
    b64_dict = base64.b64encode(bytes_dict)
    return b64_dict.decode()


def b64str_to_dict(str_data):
    b64_dict = base64.b64decode(str_data.encode())
    bytes_dict = json.loads(b64_dict)

    return bytes_dict


def bytes_to_b64str(byte_data):
    byte_data_64 = base64.b64encode(byte_data)
    byte_data_64_ascii = byte_data_64.decode('ascii')
    return byte_data_64_ascii


def b64str_to_bytes(str_data):
    str_ascii = str_data.encode('ascii')
    byte_data = base64.b64decode(str_ascii)
    return byte_data


def get_docker_path() -> str:
    """Returns the path of the docker command, or of podman as a fallback"""
    docker_path = shutil.which('docker')
    podman_path = shutil.which('podman')
    if not docker_path and not podman_path:
        raise Exception('docker/podman command not found. Install docker'
                        '/podman or use an already built runtime')
    return docker_path or podman_path


def _get_required_param(backend_config, backend: str, param: str):
    if param not in backend_config:
        raise Exception(
            f'You must provide "{param}" param in config '
            f'under "{backend}" section'
        )
    return backend_config[param]


def get_default_container_name(backend, backend_config, runtime_name):
    """
    Generates the default runtime image name, qualified with the registry the
    backend is configured to use. Used in serverless and kubernetes backends
    """
    python_version = CURRENT_PY_VERSION.replace('.', '')
    img = f'{runtime_name}-v{python_version}:{__version__}'

    docker_server = backend_config['docker_server']

    # Every registry qualifies the image with a different set of params, so
    # they are recognised by their well known hostnames
    if 'docker.io' in docker_server:
        # Docker hub container registry
        docker_user = _get_required_param(
            backend_config, backend, 'docker_user'
        )
        return f'docker.io/{docker_user}/{img}'

    elif 'icr.io' in docker_server:
        # IBM container registry
        docker_namespace = _get_required_param(
            backend_config, backend, 'docker_namespace'
        )
        return f'{docker_server}/{docker_namespace}/{img}'

    elif 'pkg.dev' in docker_server:
        # Google Artifact Registry (Docker)
        if 'region' not in backend_config or 'project_name' not in backend_config:
            raise Exception(
                'You must provide "region" and "project_name" params in '
                'config under "gcp" section'
            )
        region = backend_config['region']
        project_name = backend_config['project_name']
        repository = backend_config.get(
            'artifact_registry_repository', 'lithops'
        )
        return f'{region}-docker.pkg.dev/{project_name}/{repository}/{img}'

    else:
        return f'{docker_server}/{img}'


def _get_docker_desktop_username() -> str:
    """Reads the registry user out of the Docker Desktop credential helper"""
    cmd = (
        "docker-credential-desktop list | jq -r 'to_entries[].key' | while "
        "read; do docker-credential-desktop get <<<$REPLY; break; done"
    )
    try:
        credentials = sp.check_output(
            cmd, shell=True, encoding='UTF-8', stderr=sp.STDOUT
        )
        return json.loads(credentials)['Username']
    except Exception:
        raise Exception('Unable to get the Docker registry user')


def get_docker_username():
    """Returns the user that docker/podman is logged in to the registry as"""
    docker_path = get_docker_path()
    docker_info = sp.check_output(
        f"{docker_path} info", shell=True,
        encoding='UTF-8', stderr=sp.STDOUT
    )

    user = None
    for line in docker_info.splitlines():
        if 'Username' in line:
            _, username = line.strip().split(':')
            user = username.strip()

    return user if user is not None else _get_docker_desktop_username()


def find_free_port() -> int:
    """Returns a port that is free at this instant"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 0))
        return s.getsockname()[1]


# Schemes that name a Lithops storage backend by its protocol
_URL_SCHEME_ALIASES = {'cos': 'ibm_cos', 's3': 'aws_s3'}


def split_object_url(obj_url):
    """
    Splits a data URL into its storage backend, bucket, prefix and object
    name. A URL ending in '/' names a folder, so it has no object name
    """
    if '://' in obj_url:
        sb, path = obj_url.split('://')
    else:
        sb = None
        path = obj_url

    sb = _URL_SCHEME_ALIASES.get(sb, sb)

    bucket, full_key = path.split('/', 1) if '/' in path else (path, '')

    if full_key.endswith('/'):
        prefix, obj_name = full_key[:-1], ''
    elif '/' in full_key:
        prefix, obj_name = full_key.rsplit('/', 1)
    else:
        prefix, obj_name = '', full_key

    return sb, bucket, prefix, obj_name


def split_path(path):
    """Splits a storage path into its bucket and its key"""
    if path.startswith("/"):
        path = path[1:]
    ind = path.find("/")
    if ind > 0:
        bucket_name = path[:ind]
        key = path[ind + 1:]
    else:
        bucket_name = path
        key = None
    return bucket_name, key


def format_data(iterdata, extra_args):
    """
    Converts iterdata to a list, appending extra_args to every element. The
    element decides how: tuples are concatenated, dicts are merged
    """
    data = _as_iterdata_list(iterdata)
    if not extra_args:
        return data

    new_iterdata = []
    for data_i in data:
        if type(data_i) is tuple:
            if type(extra_args) is not tuple:
                raise Exception(
                    'extra_args must contain args in a tuple'
                )
            new_iterdata.append(data_i + extra_args)
        elif type(data_i) is dict:
            if type(extra_args) is not dict:
                raise Exception(
                    'extra_args must contain kwargs in a dictionary'
                )
            data_i.update(extra_args)
            new_iterdata.append(data_i)
        else:
            new_iterdata.append((data_i, *extra_args))
    return new_iterdata


def _as_iterdata_list(iterdata):
    if isinstance(iterdata, (range, set)):
        return list(iterdata)
    if isinstance(iterdata, list):
        return iterdata
    return [iterdata]


# Params that Lithops injects at invocation time, so the user is not expected
# to provide them in the iterdata
_INJECTED_ARGS = frozenset({'ibm_cos', 'storage', 'id', 'rabbitmq'})


def _user_signature(func) -> inspect.Signature:
    """Signature of a map function, without the params Lithops injects"""
    func_sig = inspect.signature(func)
    user_parameters = [
        param
        for name, param in func_sig.parameters.items()
        if name not in _INJECTED_ARGS
    ]
    return func_sig.replace(parameters=user_parameters)


def _chained_futures(iterdata):
    """
    The futures of a previous job used as the input of this one, or None
    when the iterdata is plain data.

    A slice of a FuturesList, or a list built from one, is a chain too: both
    lose the FuturesList type, and binding a future to a parameter as if it
    were data fails with an error that says nothing about chaining
    """
    from lithops.future import ResponseFuture

    if isinstance(iterdata, FuturesList):
        return list(iterdata)

    if not isinstance(iterdata, (list, tuple)) or not iterdata:
        return None

    futures = [
        elem for elem in iterdata if isinstance(elem, ResponseFuture)
    ]
    if not futures:
        return None
    if len(futures) != len(iterdata):
        raise ValueError(
            "The iterdata mixes futures of a previous job with plain data. "
            "Chaining takes the futures of one job as the whole input of "
            "the next one"
        )
    return list(iterdata)


def verify_args(func, iterdata, extra_args):
    """
    Binds every element of the iterdata to the params of the map function,
    returning one kwargs dict per call
    """
    chained = _chained_futures(iterdata)
    if chained is not None:
        if extra_args:
            # The worker binds the result of the previous call to the whole
            # signature, so there is no room left for these. Said here rather
            # than letting every activation fail on a missing argument
            raise ValueError(
                "extra_args is not supported when chaining jobs: a chained "
                "function is called with the result of the previous one and "
                "nothing else. Return the extra values from the previous "
                "function, or get its results and start a new job with them"
            )
        # A chained job receives the future of the previous one, which is only
        # bound to a param once the previous job finishes
        return [{'future': f} for f in chained]

    data = format_data(iterdata, extra_args)
    func_sig = _user_signature(func)

    # A wrapper, such as a decorator, hides the params of the function behind
    # **kwargs, so the names of a dict element cannot be checked against them
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in func_sig.parameters.values()
    )

    new_data = []

    for elem in data:
        if isinstance(elem, dict):
            if has_var_keyword or set(func_sig.parameters) <= set(elem):
                new_data.append(elem)
            else:
                raise ValueError(
                    "Check the args names in the data. You provided these "
                    f"args: {list(elem)}, and the args must be: "
                    f"{list(func_sig.parameters)}"
                )
        elif isinstance(elem, tuple):
            new_data.append(dict(func_sig.bind(*elem).arguments))
        else:
            # A single value of any other type binds to the first param
            new_data.append(dict(func_sig.bind(elem).arguments))

    return new_data


class WrappedStreamingBody:
    """
    Wrap boto3's StreamingBody object to provide enough
    Python fileobj functionality.

    from https://gist.github.com/debedb/2e5cbeb54e43f031eaf0
    """
    def __init__(self, sb, size):
        self.sb = sb
        self.pos = 0
        self.size = size

    def tell(self):
        return self.pos

    def read(self, n=None):
        retval = self.sb.read(n)
        if retval == "":
            raise EOFError()
        self.pos += len(retval)
        return retval

    def readline(self):
        try:
            retval = self.sb.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)
        return retval

    def seek(self, offset, whence=0):
        retval = self.pos
        if whence == 2:
            if offset == 0:
                retval = self.size
            else:
                raise Exception("Unsupported")
        elif whence == 1:
            offset = self.pos + offset
            if offset > self.size:
                retval = self.size
            else:
                retval = offset

        self.pos = retval
        return retval

    def __str__(self):
        return "WrappedBody"

    def __iter__(self):
        return self

    def __next__(self):
        return self.read(64 * 1024)

    def __getattr__(self, attr):
        # Only reached for the attributes this wrapper does not define, so
        # everything else of the fileobj protocol falls through to boto3
        return getattr(self.sb, attr)


class WrappedStreamingBodyPartition(WrappedStreamingBody):
    """
    Wrap boto3's StreamingBody object to provide line
    integrity of the partitions based on the newline
    character.
    """
    def __init__(self, sb, size, byterange, newline='\n'):
        super().__init__(sb, size)
        self.range = byterange
        self.newline_char = newline.encode()
        # Every chunk but the first one reads one byte early, so that read()
        # can tell whether the previous chunk ended in the middle of a row
        self._plusbytes = 0 if not self.range or self.range[0] == 0 else 1
        self._first_byte = None
        self._eof = False
        self._first_read = True

    def read(self, n=None):
        if self._eof:
            return b''

        if not self._first_byte and self._plusbytes == 1:
            self._first_byte = self.sb.read(self._plusbytes)

        retval = self.sb.read(n)
        last_row_end_pos = len(retval)
        self.pos += last_row_end_pos
        first_row_start_pos = 0

        if self._first_read and self._first_byte and \
           self._first_byte != self.newline_char:
            # The previous chunk did not end in a newline, so the first row of
            # this one is a cut row that the previous chunk already returned
            logger.debug('Discarding first partial row')
            first_row_start_pos = retval.find(self.newline_char) + 1
            self._first_read = False

        # The last row of a chunk is completed past its own end
        if self.pos >= self.size:
            current_end_pos = last_row_end_pos - (self.pos - self.size)
            last_byte_pos = retval[current_end_pos - 1:].find(self.newline_char)
            last_row_end_pos = current_end_pos + last_byte_pos
            self._eof = True

        return retval[first_row_start_pos:last_row_end_pos]

    def readline(self):
        if self._eof:
            return b''

        if not self._first_byte and self._plusbytes == 1:
            self._first_byte = self.sb.read(self._plusbytes)
            if self._first_byte != self.newline_char:
                logger.debug('Discarding first partial row')
                self.sb._raw_stream.readline()
        try:
            retval = self.sb._raw_stream.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)

        if self.pos >= self.size:
            self._eof = True

        return retval


def docker_login(docker_user, docker_password, docker_server):
    """
    Log in to a container registry using docker/podman.

    Docker Hub must be logged in without an explicit server host, matching
    `docker login -u USER --password-stdin`.
    """
    if not docker_user or not docker_password:
        raise Exception('docker_user and docker_password are required')
    if not docker_server:
        raise Exception('docker_server is required')

    docker_path = get_docker_path()
    docker_password = docker_password.strip()

    if 'docker.io' in docker_server:
        cmd = f'{docker_path} login -u {docker_user} --password-stdin'
    else:
        cmd = (f'{docker_path} login -u {docker_user} --password-stdin '
               f'{docker_server}')

    logger.debug('Logging in to container registry')
    run_command(cmd, input=docker_password)


def run_command(cmd, return_result=False, input=None):
    """
    Runs a shell command, silencing its output unless lithops is in debug
    mode. Returns its stdout if asked to, otherwise nothing
    """
    quiet = logger.getEffectiveLevel() != logging.DEBUG
    kwargs = {'stderr': sp.DEVNULL} if quiet else {}

    if input:
        return sp.check_output(
            cmd.split(),
            input=bytes(input, 'utf-8'),
            **kwargs,
        )

    if return_result:
        result = sp.check_output(cmd.split(), encoding='UTF-8', **kwargs)
        return result.strip().replace('"', '')

    if quiet:
        kwargs['stdout'] = sp.DEVNULL
    sp.check_call(cmd.split(), **kwargs)


def is_podman(docker_path) -> bool:
    """Checks whether the docker command is actually podman"""
    try:
        cmd = f'{docker_path} info | grep podman'
        sp.check_output(cmd, shell=True, stderr=sp.STDOUT)
        return True
    except Exception:
        return False


class BackendType(Enum):
    BATCH = 'batch'
    FAAS = 'faas'


class CountDownLatch:
    """
    Barrier that blocks the waiters until it has been unlocked as many times
    as the count it was created with
    """

    def __init__(self, count):
        self.count = count
        self.event = threading.Event()
        self.lock = threading.Lock()

    def unlock(self):
        with self.lock:
            self.count -= 1
            if self.count == 0:
                self.event.set()

    def wait(self):
        if self.count > 0:
            self.event.wait()

    @property
    def done(self):
        return self.count == 0


CURRENT_PY_VERSION = version_str(sys.version_info)
