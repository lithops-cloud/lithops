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
import sys
import pkgutil
import logging
import pickle
import platform
import subprocess
from contextlib import contextmanager

from lithops.version import __version__ as lithops_ver
from lithops.utils import sizeof_fmt, is_unix_system, b64str_to_bytes
from lithops.constants import MODULES_DIR, SA_INSTALL_DIR, LITHOPS_TEMP_DIR

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


def get_function_and_modules(job, internal_storage):
    """
    Gets the function and modules from storage
    """
    logger.info("Getting function and modules")
    backend = job.config['lithops']['backend']
    func_path = '/'.join([LITHOPS_TEMP_DIR, job.func_key])
    func_obj = None

    if job.config[backend].get('runtime_include_function'):
        logger.info("Runtime include function feature activated. Loading "
                    "function/mods from local runtime")
        func_path = '/'.join([SA_INSTALL_DIR, job.func_key])
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

        for m_filename, m_data in loaded_func_all['module_data'].items():
            m_path = os.path.dirname(m_filename)

            if len(m_path) > 0 and m_path[0] == "/":
                m_path = m_path[1:]
            to_make = os.path.join(module_path, m_path)
            try:
                os.makedirs(to_make)
            except OSError as e:
                if e.errno == 17:
                    pass
                else:
                    raise e
            full_filename = os.path.join(to_make, os.path.basename(m_filename))
            # logger.debug('Writing {}'.format(full_filename))

            with open(full_filename, 'wb') as fid:
                fid.write(b64str_to_bytes(m_data))

    return loaded_func_all['func']


def get_function_data(job, internal_storage):
    """
    Get function data (iteradata) from storage
    """
    if job.data_key:
        extra_get_args = {}
        if job.data_byte_ranges is not None:
            init_byte = job.data_byte_ranges[0][0]
            last_byte = job.data_byte_ranges[-1][1]
            range_str = f'bytes={init_byte}-{last_byte}'
            extra_get_args['Range'] = range_str

        logger.info("Loading function data parameters from storage")
        data_obj = internal_storage.get_data(job.data_key, extra_get_args=extra_get_args)

        loaded_data = []
        offset = 0
        if job.data_byte_ranges is not None:
            for dbr in job.data_byte_ranges:
                length = dbr[1] - dbr[0] + 1
                loaded_data.append(data_obj[offset:offset + length])
                offset += length
        else:
            loaded_data.append(data_obj)
    else:
        loaded_data = [eval(byte_str) for byte_str in job.data_byte_strs]

    return loaded_data


def get_memory_usage(formatted=True):
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
    sorted_cmds, shareds, count, total, swaps, total_swap = \
        ps_mem.get_memory_usage(pids_to_show, split_args, discriminate_by_pid,
                                include_self=True, only_self=False)
    if formatted:
        return sizeof_fmt(int(ps_mem.human(total, units=1)))
    else:
        return int(ps_mem.human(total, units=1))


def peak_memory():
    """Return the peak memory usage in bytes."""
    if not is_unix_system():
        return None
    ru_maxrss = getrusage(RUSAGE_SELF).ru_maxrss
    # note that on Linux ru_maxrss is in KiB, while on Mac it is in bytes
    # see https://pythonspeed.com/articles/estimating-memory-usage/#measuring-peak-memory-usage
    return ru_maxrss * 1024 if platform.system() == "Linux" else ru_maxrss


def free_disk_space(dirname):
    """
    Returns the number of free bytes on the mount point containing DIRNAME
    """
    s = os.statvfs(dirname)
    return s.f_bsize * s.f_bavail


def get_server_info():
    """
    Returns server information
    """
    container_name = subprocess.check_output("uname -n", shell=True).decode("ascii").strip()
    ip_addr = subprocess.check_output("hostname -I", shell=True).decode("ascii").strip()
    cores = subprocess.check_output("nproc", shell=True).decode("ascii").strip()

    cmd = "cat /sys/class/net/eth0/speed | awk '{print $0 / 1000\"GbE\"}'"
    net_speed = subprocess.check_output(cmd, shell=True).decode("ascii").strip()

    # cmd = "cat /sys/class/net/eth0/address"
    # mac_address = subprocess.check_output(cmd, shell=True).decode("ascii").strip()

    cmd = "grep MemTotal /proc/meminfo | awk '{print $2 / 1024 / 1024\"GB\"}'"
    memory = subprocess.check_output(cmd, shell=True).decode("ascii").strip()

    server_info = {'container_name': container_name,
                   'ip_address': ip_addr,
                   'net_speed': net_speed,
                   'cores': cores,
                   'memory': memory}
    """
    if os.path.exists("/proc"):
        server_info.update({'/proc/cpuinfo': open("/proc/cpuinfo", 'r').read(),
                            '/proc/meminfo': open("/proc/meminfo", 'r').read(),
                            '/proc/self/cgroup': open("/proc/meminfo", 'r').read(),
                            '/proc/cgroups': open("/proc/cgroups", 'r').read()})
    """
    return server_info


def get_runtime_metadata():
    """
    Generates the runtime metadata needed for lithops
    """
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta["python_version"] = str(python_version[0]) + "." + str(python_version[1])
    runtime_meta["lithops_version"] = lithops_ver

    return runtime_meta


def memory_monitor_worker(mm_conn, delay=0.01):
    """
    Monitor that checks the current memory usage
    """
    peak = 0

    logger.debug("Starting memory monitor")

    def make_measurement(peak):
        mem = get_memory_usage(formatted=False) + 5 * 1024**2
        if mem > peak:
            peak = mem
        return peak

    while not mm_conn.poll(delay):
        try:
            peak = make_measurement(peak)
        except Exception:
            break

    try:
        peak = make_measurement(peak)
    except Exception as e:
        logger.error('Memory monitor: {}'.format(e))
    mm_conn.send(peak)


@contextmanager
def custom_redirection(fileobj):
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

    def __init__(self, stream):
        self._stdout = sys.stdout
        self._stream = stream

    def write(self, log):
        self._stdout.write(log)
        try:
            self._stream.write(log)
            self.flush()
        except ValueError:
            pass

    def flush(self):
        try:
            self._stream.flush()
            self._stdout.flush()
        except ValueError:
            pass

    def fileno(self):
        return self._stdout.fileno()


class SystemMonitor:

    def __init__(self, process_id=None):
        """
        Initialize the SystemMonitor.
        If process_id is None, monitor the current process.
        """
        self.process_id = process_id
        self.cpu_usage = []
        self.process = None
        self.cpu_times = None
        self.current_net_io = None
        self.mem_info = None

    def start(self):
        """
        Start monitoring.
        """
        if not psutil_found:
            return

        self.process = psutil.Process(self.process_id)

        # record the initial CPU usage (to be ignored).
        psutil.cpu_percent(interval=None, percpu=True)

        # Reset the network IO counters cache and baseline.
        psutil.net_io_counters.cache_clear()
        self.start_net_io = psutil.net_io_counters()

    def stop(self):
        """
        Stop monitoring.
        """
        if not psutil_found:
            return

        # Record the CPU usage since the last call (start).
        self.cpu_usage = psutil.cpu_percent(interval=None, percpu=True)
        self.cpu_times = psutil.cpu_times()
        self.current_net_io = psutil.net_io_counters()
        self.mem_info = self.process.memory_full_info()

    def get_cpu_info(self):
        """
        Return CPU usage, system time, and user time for each CPU core.
        """
        if not psutil_found:
            return {"usage": [], "system": 0, "user": 0}

        return {"usage": self.cpu_usage, "system": self.cpu_times.system, "user": self.cpu_times.user}

    def get_network_io(self):
        """
        Calculate network IO (bytes sent and received) since the last reset.
        """
        if not psutil_found:
            return {"sent": 0, "recv": 0}

        bytes_sent = self.current_net_io.bytes_sent - self.start_net_io.bytes_sent
        bytes_recv = self.current_net_io.bytes_recv - self.start_net_io.bytes_recv
        return {"sent": bytes_sent, "recv": bytes_recv}

    def get_memory_info(self):
        """
        Get memory usage information of the monitored process.
        """
        if not psutil_found:
            return {"rss": 0, "vms": 0, "uss": 0}

        return {"rss": self.mem_info.rss, "vms": self.mem_info.vms, "uss": self.mem_info.uss}
