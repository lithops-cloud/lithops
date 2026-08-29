import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

# Paramiko logs full tracebacks on transient boot-time failures (banner EOF,
# port closed, etc.). Lithops already retries; keep paramiko quiet.
for _log_name in ('paramiko', 'paramiko.transport', 'paramiko.client'):
    logging.getLogger(_log_name).setLevel(logging.CRITICAL)

_DEFAULT_KEY = os.path.expanduser('~/.ssh/id_rsa')


def ssh_boot_status_message(err: BaseException) -> str:
    """
    Maps a transient SSH error raised while a VM boots to a short status
    message, falling back to the error itself when it is not a known one
    """
    msg = str(err).lower()
    if 'timed out' in msg or 'timeout' in msg:
        return 'VM is starting, waiting for network/SSH'
    if 'unable to connect' in msg or 'connection refused' in msg:
        return 'VM is up, starting SSH service'
    if 'banner' in msg or 'no existing session' in msg or 'connection reset' in msg:
        return 'Configuring SSH on VM'
    return str(err)


class SSHClient:
    """
    Runs commands and transfers files on a remote host over SSH. The
    connection is created on first use and reused afterwards
    """

    def __init__(self, ip_address: str, ssh_credentials: Dict[str, Any]):
        self.ip_address = ip_address
        self.ssh_credentials = ssh_credentials
        self.ssh_client = None

        if 'key_filename' in self.ssh_credentials:
            fpath = os.path.expanduser(self.ssh_credentials['key_filename'])
            self.ssh_credentials['key_filename'] = fpath
            if not os.path.exists(fpath):
                logger.debug(
                    f"Private key file {fpath} does not exist. "
                    "Trying with the default key"
                )
                self.ssh_credentials['key_filename'] = _DEFAULT_KEY

    def close(self) -> None:
        """Closes the connection, if there is one, and forgets about it"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                # A connection that cannot be closed is dropped anyway
                pass
        self.ssh_client = None

    def create_client(self, timeout: int = 2) -> paramiko.SSHClient:
        """Opens a new connection, replacing the current one"""
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': self.ip_address,
            'username': self.ssh_credentials.get('username'),
            'password': self.ssh_credentials.get('password'),
            'timeout': timeout,
            'banner_timeout': 200,
            'allow_agent': False,
            'look_for_keys': False,
        }
        key_filename = self.ssh_credentials.get('key_filename')
        if key_filename:
            connect_kwargs['key_filename'] = key_filename

        # Only kept once connected, so that a failed connect does not leave
        # a client behind for _ensure_client to reuse
        ssh_client.connect(**connect_kwargs)
        self.ssh_client = ssh_client
        logger.debug(f"{self.ip_address} ssh client created")
        return self.ssh_client

    def _ensure_client(self) -> paramiko.SSHClient:
        if self.ssh_client is None:
            self.create_client()
        return self.ssh_client

    @contextmanager
    def _sftp(self):
        ftp_client = self._ensure_client().open_sftp()
        try:
            yield ftp_client
        finally:
            ftp_client.close()

    def _exec_command(self, cmd: str, timeout: Optional[int]):
        return self.ssh_client.exec_command(cmd, timeout=timeout)

    def run_remote_command(
        self, cmd: str, timeout: Optional[int] = None, run_async: bool = False
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Runs a command on the remote host and returns its stdout and stderr,
        or a pair of Nones when asked not to wait for it to complete
        """
        if not self.ip_address or self.ip_address == '0.0.0.0':
            raise Exception('Invalid IP Address')

        self._ensure_client()
        # stdin is kept until this returns: closing it, which garbage
        # collection does, sends EOF to the command still being read below
        try:
            stdin, stdout, stderr = self._exec_command(cmd, timeout)
        except Exception:
            # The reused connection may have died since the last command
            self.create_client()
            stdin, stdout, stderr = self._exec_command(cmd, timeout)

        if run_async:
            return None, None
        return stdout.read().decode().strip(), stderr.read().decode().strip()

    def download_remote_file(self, remote_src: str, local_dst: str) -> None:
        """Downloads a remote file, creating the local directory if needed"""
        dirname = os.path.dirname(local_dst)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with self._sftp() as ftp_client:
            ftp_client.get(remote_src, local_dst)

    def upload_local_file(self, local_src: str, remote_dst: str) -> None:
        """Uploads a local file to a remote destination"""
        with self._sftp() as ftp_client:
            ftp_client.put(local_src, remote_dst)

    def upload_multiple_local_files(
        self, file_list: List[Tuple[str, str]]
    ) -> None:
        """Uploads several local files reusing a single SFTP connection"""
        with self._sftp() as ftp_client:
            for local_src, remote_dst in file_list:
                ftp_client.put(local_src, remote_dst)

    def upload_data_to_file(self, data: str, remote_dst: str) -> None:
        """Writes data into a remote file"""
        with self._sftp() as ftp_client:
            with ftp_client.open(remote_dst, 'w') as remote_file:
                remote_file.write(data)
