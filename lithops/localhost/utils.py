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
import signal
import shutil
import logging
import tempfile
from typing import Iterable, List, Optional

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

from lithops.constants import LITHOPS_TEMP_DIR

_COPY_IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')


# (lithops_location, temp_dir, fingerprint) triples this process has copied
_COPIED_PACKAGES = set()


def _source_fingerprint(lithops_location: str) -> tuple:
    """
    How many source files the package has and when the newest was written.

    Cheap enough to check on every executor (a stat per file, no reads), and
    enough to notice the edits of a development install, where the package
    does change under a running process
    """
    newest = 0.0
    count = 0
    for dirpath, dirnames, filenames in os.walk(lithops_location):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for filename in filenames:
            if filename.endswith(('.pyc', '.pyo')):
                continue
            count += 1
            try:
                mtime = os.stat(os.path.join(dirpath, filename)).st_mtime
            except OSError:
                continue
            newest = max(newest, mtime)
    return count, newest


def copy_lithops_package(
    lithops_location: str,
    runner_src: str,
    runner_dst: str,
    temp_dir: str = LITHOPS_TEMP_DIR,
) -> None:
    """
    Copies the Lithops package into the local temp dir and installs the runner.

    Concurrent FunctionExecutor setups share this destination. Copy into a
    staging directory first, then replace the destination under a file lock
    so one rmtree cannot delete another copy mid-flight. Bytecode caches are
    omitted because pytest and other processes rewrite them while we copy.

    Every FunctionExecutor calls this, so the tree is copied once and only
    checked afterwards. Repeating it means one copytree of the whole
    package per executor, each taking the cross-process lock, which
    serialises executors that have nothing to do with each other, and
    sessions running side by side. It is copied again if the destination
    has gone missing, or if the source changed, which a development
    install does under a running process.

    The runner is installed on every call, never skipped, and put in place
    with a rename: a plain copy truncates the destination before writing
    it, and a task process of another session starting in that window
    would exec a half-written file.
    """
    os.makedirs(temp_dir, exist_ok=True)
    dst_path = os.path.join(temp_dir, 'lithops')
    lock_path = os.path.join(temp_dir, '.lithops-copy.lock')

    package_key = (
        lithops_location, temp_dir, _source_fingerprint(lithops_location)
    )
    if package_key not in _COPIED_PACKAGES or not os.path.isdir(dst_path):
        staging = tempfile.mkdtemp(prefix='lithops-src-', dir=temp_dir)
        try:
            shutil.copytree(
                lithops_location,
                os.path.join(staging, 'lithops'),
                ignore=_COPY_IGNORE,
            )
            with open(lock_path, 'a') as lock_file:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    shutil.rmtree(dst_path, ignore_errors=True)
                    shutil.move(os.path.join(staging, 'lithops'), dst_path)
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            _COPIED_PACKAGES.add(package_key)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # Staged under a name of this process, then renamed over the
    # destination, which is atomic on the same filesystem
    runner_tmp = f'{runner_dst}.{os.getpid()}.tmp'
    try:
        shutil.copyfile(runner_src, runner_tmp)
        os.replace(runner_tmp, runner_dst)
    finally:
        if os.path.exists(runner_tmp):
            os.remove(runner_tmp)


def decode_process_output(data: Optional[object]) -> str:
    """
    Returns the captured output of a process as text, empty if there is none
    """
    if isinstance(data, bytes):
        return data.decode('utf-8', errors='replace').strip()
    if isinstance(data, str):
        return data.strip()
    return ''


def _read_log_tail(log_file: str, lines: int = 80) -> str:
    if not os.path.isfile(log_file):
        return ''
    try:
        with open(log_file, 'r', errors='replace') as fh:
            return ''.join(fh.readlines()[-lines:]).strip()
    except OSError:
        return ''


def log_process_failure(
    logger: logging.Logger,
    message: str,
    stdout: Optional[object] = None,
    stderr: Optional[object] = None,
    log_file: Optional[str] = None,
) -> None:
    """
    Logs a localhost worker crash. Reports what the process printed, or the
    tail of the runner log when it died without printing anything, as that is
    where an import error or a missing dependency shows up
    """
    logger.error(message)
    detail = decode_process_output(stderr) or decode_process_output(stdout)
    if detail:
        logger.error(detail)
        return

    tail = _read_log_tail(log_file) if log_file else ''
    if tail:
        logger.error(f'Runner log:\n{tail}')


def kill_process(process, is_unix: bool) -> None:
    """
    Kills a running subprocess. On Unix the whole process group goes down, so
    that the workers the runner forked do not outlive it
    """
    if not process or process.poll() is not None:
        return
    pid = process.pid
    if is_unix:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    else:
        os.kill(pid, signal.SIGTERM)


def docker_pull_cmd(docker_path: str, image: str) -> List[str]:
    """Builds the command that pulls a runtime image"""
    return [docker_path, 'pull', image]


def docker_rm_cmd(docker_path: str, name: str) -> List[str]:
    """Builds the command that force removes a container"""
    return [docker_path, 'rm', '-f', name]


def docker_run_cmd(
    docker_path: str,
    image: str,
    *,
    name: str,
    tmp_path: str,
    uid: Optional[int] = None,
    gid: Optional[int] = None,
    is_podman: bool = False,
    use_gpu: bool = False,
    extra_run_args: Optional[Iterable[str]] = None,
    entrypoint: Optional[str] = 'python3',
    container_args: Optional[Iterable[str]] = None,
) -> List[str]:
    """
    Builds the command that runs a container with the local temp dir mounted
    on /tmp, which is how the runner and the job files reach the container.

    Podman maps the calling user into the container by itself, so --user is
    only passed to Docker.
    """
    cmd = [docker_path, 'run', '--name', name]
    if use_gpu:
        cmd.extend(['--gpus', 'all'])
    if uid is not None and gid is not None and not is_podman:
        cmd.extend(['--user', f'{uid}:{gid}'])
    cmd.extend([
        '--env', f'USER={os.getenv("USER", "root")}',
        '--rm', '-v', f'{tmp_path}:/tmp',
    ])
    if extra_run_args:
        cmd.extend(extra_run_args)
    if entrypoint is not None:
        cmd.extend(['--entrypoint', entrypoint])
    cmd.append(image)
    if container_args:
        cmd.extend(container_args)
    return cmd


def docker_exec_python_cmd(
    docker_path: str,
    container_name: str,
    script_path: str,
    *script_args: str,
) -> List[str]:
    """Builds the command that runs a Python script in a running container"""
    inner = ' '.join(['python3', script_path, *script_args])
    return [
        docker_path, 'exec', container_name, '/bin/bash', '-c', inner
    ]
