import os
import sys
import pkgutil
import subprocess
from lithops.utils import sizeof_fmt, is_unix_system

if is_unix_system():
    # Windows hosts can't use ps_mem module
    import ps_mem


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


def get_runtime_preinstalls():
    """
    Generates the runtime metadata needed for lithops
    """
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta["python_ver"] = str(python_version[0])+"."+str(python_version[1])

    return runtime_meta
