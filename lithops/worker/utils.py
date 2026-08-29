#
# (C) Copyright Cloudlab URV 2021
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
import posixpath
import sys
import ast
import pkgutil
import logging
import pickle
import platform
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

from lithops.version import __version__ as lithops_ver
from lithops.utils import sizeof_fmt, is_unix_system
from lithops.constants import MODULES_DIR, SA_INSTALL_DIR
from lithops.job.serialize import write_module_data

try:
    import psutil
    psutil_found = True
except ModuleNotFoundError:
    psutil_found = False


logger = logging.getLogger(__name__)


if is_unix_system():
    from resource import RUSAGE_SELF, getrusage
    # Windows hosts can't use ps_mem module
    import ps_mem


def get_function_and_modules(job: SimpleNamespace, internal_storage) -> bytes:
    """
    Gets the pickled function from storage, and writes the modules it depends
    on where the interpreter can import them
    """
    logger.info("Getting function and modules")
    backend = job.config['lithops']['backend']

    if job.config[backend].get('runtime_include_function'):
        logger.info(
            "Runtime include function feature activated. Loading "
            "function/mods from local runtime"
        )
        # Custom runtimes live on Linux images under /opt/lithops.
        func_path = posixpath.join(SA_INSTALL_DIR, job.func_key)
        with open(func_path, "rb") as f:
            func_obj = f.read()
    else:
        logger.info(f"Loading {job.func_key} from storage")
        func_obj = internal_storage.get_func(job.func_key)

    loaded_func_all = pickle.loads(func_obj)

    if loaded_func_all.get('module_data'):
        module_path = os.path.join(MODULES_DIR, job.job_key)
        logger.info(f"Writing function dependencies to {module_path}")
        os.makedirs(module_path, exist_ok=True)
        sys.path.append(module_path)
        write_module_data(module_path, loaded_func_all['module_data'])

    return loaded_func_all['func']


def _decode_data_byte_str(byte_str: Union[bytes, str]) -> bytes:
    if isinstance(byte_str, bytes):
        return byte_str
    return ast.literal_eval(byte_str)


def get_function_data(job: SimpleNamespace, internal_storage) -> List[bytes]:
    """
    Gets the function data (iterdata) of every task of the job, either from
    storage or from the invocation payload
    """
    if job.data_key:
        extra_get_args = {}
        if job.data_byte_ranges:
            init_byte = job.data_byte_ranges[0][0]
            last_byte = job.data_byte_ranges[-1][1]
            extra_get_args['Range'] = f'bytes={init_byte}-{last_byte}'

        logger.info("Loading function data parameters from storage")
        data_obj = internal_storage.get_data(
            job.data_key, extra_get_args=extra_get_args
        )

        loaded_data = []
        offset = 0
        if job.data_byte_ranges:
            for dbr in job.data_byte_ranges:
                length = dbr[1] - dbr[0] + 1
                loaded_data.append(data_obj[offset:offset + length])
                offset += length
        else:
            loaded_data.append(data_obj)
    else:
        loaded_data = [
            _decode_data_byte_str(byte_str) for byte_str in job.data_byte_strs
        ]

    return loaded_data


def get_memory_usage(formatted: bool = True) -> Optional[Union[str, int]]:
    """
    Gets the current memory usage of the runtime.
    To be used only in the action code.
    """
    if not is_unix_system() or os.geteuid() != 0:
        # Non Unix systems and non root users can't run
        # the ps_mem module
        return

    split_args = False
    pids_to_show = None
    discriminate_by_pid = False

    ps_mem.verify_environment(pids_to_show)
    _, _, _, total, _, _ = ps_mem.get_memory_usage(
        pids_to_show, split_args, discriminate_by_pid,
        include_self=True, only_self=False
    )
    if formatted:
        return sizeof_fmt(int(ps_mem.human(total, units=1)))
    return int(ps_mem.human(total, units=1))


def peak_memory() -> Optional[int]:
    """Returns the peak memory usage in bytes"""
    if not is_unix_system():
        return None
    ru_maxrss = getrusage(RUSAGE_SELF).ru_maxrss
    # note that on Linux ru_maxrss is in KiB, while on Mac it is in bytes
    # see https://pythonspeed.com/articles/estimating-memory-usage/#measuring-peak-memory-usage
    return ru_maxrss * 1024 if platform.system() == "Linux" else ru_maxrss


def free_disk_space(dirname: str) -> int:
    """
    Returns the number of free bytes on the mount point containing DIRNAME
    """
    s = os.statvfs(dirname)
    return s.f_bsize * s.f_bavail


def _shell_output(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True).decode("ascii").strip()


def get_server_info() -> Dict[str, str]:
    """
    Returns information about the machine this worker runs on
    """
    net_speed_cmd = "cat /sys/class/net/eth0/speed | awk '{print $0 / 1000\"GbE\"}'"
    memory_cmd = "grep MemTotal /proc/meminfo | awk '{print $2 / 1024 / 1024\"GB\"}'"

    return {
        'container_name': _shell_output("uname -n"),
        'ip_address': _shell_output("hostname -I"),
        'net_speed': _shell_output(net_speed_cmd),
        'cores': _shell_output("nproc"),
        'memory': _shell_output(memory_cmd),
    }


def get_runtime_metadata() -> Dict[str, Any]:
    """
    Generates the runtime metadata needed for lithops
    """
    return {
        "preinstalls": sorted(
            [mod, is_pkg] for _, mod, is_pkg in pkgutil.iter_modules()
        ),
        "python_version": f"{sys.version_info[0]}.{sys.version_info[1]}",
        "lithops_version": lithops_ver,
    }


def memory_monitor_worker(mm_conn, delay: float = 0.01) -> None:
    """
    Monitors the memory usage of the runtime until the connection is ready,
    and reports the peak back through it
    """
    peak = 0

    logger.debug("Starting memory monitor")

    if get_memory_usage(formatted=False) is None:
        # Nothing to measure here, so there is no point in polling
        logger.debug("Memory monitor: memory usage is not available")
        mm_conn.send(peak)
        return

    def make_measurement(peak):
        mem = get_memory_usage(formatted=False) + 5 * 1024**2
        return max(peak, mem)

    while not mm_conn.poll(delay):
        try:
            peak = make_measurement(peak)
        except Exception:
            break

    try:
        peak = make_measurement(peak)
    except Exception as e:
        logger.error(f'Memory monitor: {e}')
    mm_conn.send(peak)


@contextmanager
def custom_redirection(fileobj):
    """Redirects stdout and stderr to fileobj for the duration of the block"""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = fileobj
    sys.stderr = fileobj
    try:
        yield fileobj
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


class LogStream:
    """
    Tees what the task prints to both the real stdout, so that it shows up in
    the logs of the backend, and the task log file
    """

    def __init__(self, stream):
        self._stdout = sys.stdout
        self._stream = stream

    def write(self, log: str) -> None:
        """Writes to the log file, unless the handler closed it already"""
        self._stdout.write(log)
        try:
            self._stream.write(log)
            self.flush()
        except ValueError:
            pass

    def flush(self) -> None:
        """Flushes both streams, unless the log file is closed already"""
        try:
            self._stream.flush()
            self._stdout.flush()
        except ValueError:
            pass

    def fileno(self) -> int:
        """Reports the descriptor of the real stdout"""
        return self._stdout.fileno()


class SystemMonitor:
    """
    Measures the resources that a process consumed between start() and
    stop(). Monitors the current process if no process id is given
    """

    def __init__(self, process_id: Optional[int] = None):
        self.process_id = process_id
        self.cpu_usage = []
        self.process = None
        self.cpu_times = None
        self.start_net_io = None
        self.current_net_io = None
        self.mem_info = None

    def start(self) -> None:
        """
        Starts monitoring, taking the baseline that stop() measures against
        """
        if not psutil_found:
            return

        self.process = psutil.Process(self.process_id)

        # The first measurement covers the whole life of the process, and is
        # meant to be ignored: the next one is relative to this one
        psutil.cpu_percent(interval=None, percpu=True)

        # psutil caches the counters, so they have to be cleared to get a
        # fresh baseline
        psutil.net_io_counters.cache_clear()
        self.start_net_io = psutil.net_io_counters()

    def stop(self) -> None:
        """
        Stops monitoring, recording everything consumed since start()
        """
        if not psutil_found:
            return

        self.cpu_usage = psutil.cpu_percent(interval=None, percpu=True)
        self.cpu_times = psutil.cpu_times()
        self.current_net_io = psutil.net_io_counters()
        self.mem_info = self.process.memory_full_info()

    def get_cpu_info(self) -> Dict[str, Any]:
        """
        Returns the CPU usage of every core, and the system and user time
        """
        if not psutil_found:
            return {"usage": [], "system": 0, "user": 0}

        return {
            "usage": self.cpu_usage,
            "system": self.cpu_times.system,
            "user": self.cpu_times.user,
        }

    def get_network_io(self) -> Dict[str, int]:
        """
        Returns the bytes sent and received while monitoring
        """
        if not psutil_found:
            return {"sent": 0, "recv": 0}

        return {
            "sent": self.current_net_io.bytes_sent - self.start_net_io.bytes_sent,
            "recv": self.current_net_io.bytes_recv - self.start_net_io.bytes_recv,
        }

    def get_memory_info(self) -> Dict[str, int]:
        """
        Returns the memory usage of the monitored process
        """
        if not psutil_found:
            return {"rss": 0, "vms": 0, "uss": 0}

        return {
            "rss": self.mem_info.rss,
            "vms": self.mem_info.vms,
            "uss": self.mem_info.uss,
        }
