import paramiko
import logging
import os
import time

logger = logging.getLogger(__name__)

# Paramiko logs full tracebacks on transient boot-time failures (banner EOF,
# port closed, etc.). Lithops already retries; keep paramiko quiet.
for _log_name in ('paramiko', 'paramiko.transport', 'paramiko.client'):
    logging.getLogger(_log_name).setLevel(logging.CRITICAL)


def ssh_boot_status_message(err):
    """
    Map transient SSH errors during VM boot to a short user-facing status.
    """
    msg = str(err).lower()
    if 'timed out' in msg or 'timeout' in msg:
        return 'VM is starting, waiting for network/SSH'
    if 'unable to connect' in msg or 'connection refused' in msg:
        return 'VM is up, starting SSH service'
    if 'banner' in msg or 'no existing session' in msg or 'connection reset' in msg:
        return 'Configuring SSH on VM'
    return str(err)


class SSHClient():

    def __init__(self, ip_address, ssh_credentials):
        self.ip_address = ip_address
        self.ssh_credentials = ssh_credentials
        self.ssh_client = None

        if 'key_filename' in self.ssh_credentials:
            fpath = os.path.expanduser(self.ssh_credentials['key_filename'])
            self.ssh_credentials['key_filename'] = fpath
            if not os.path.exists(fpath):
                logger.debug(f"Private key file {fpath} doesn't exist. Trying with the default key")
                self.ssh_credentials['key_filename'] = os.path.expanduser('~/.ssh/id_rsa')

    def close(self):
        """
        Closes the SSH client connection
        """
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
        self.ssh_client = None

    def _is_transient_ssh_error(self, err):
        if isinstance(err, (paramiko.SSHException, TimeoutError, OSError)):
            return True
        msg = str(err).lower()
        return any(s in msg for s in (
            'banner', 'timed out', 'timeout', 'unable to connect',
            'no existing session', 'connection reset', 'connection refused',
        ))

    def create_client(self, timeout=2, retries=3, retry_delay=1):
        """
        Create the SSH client connection, retrying transient boot-time errors.
        """
        last_err = None
        for attempt in range(retries):
            try:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                user = self.ssh_credentials.get('username')
                password = self.ssh_credentials.get('password')
                pkey = None

                if self.ssh_credentials.get('key_filename'):
                    with open(self.ssh_credentials['key_filename']) as f:
                        pkey = paramiko.RSAKey.from_private_key(f)

                self.ssh_client.connect(
                    self.ip_address, username=user,
                    password=password, pkey=pkey,
                    timeout=timeout, banner_timeout=200,
                    allow_agent=False, look_for_keys=False
                )

                logger.debug(f"{self.ip_address} ssh client created")
                return self.ssh_client
            except Exception as err:
                last_err = err
                self.close()
                if attempt < retries - 1 and self._is_transient_ssh_error(err):
                    logger.debug(
                        f"{self.ip_address}: {ssh_boot_status_message(err)} "
                        f"(retry {attempt + 1}/{retries})"
                    )
                    time.sleep(retry_delay)
                    continue
                raise last_err

    def run_remote_command(self, cmd, timeout=None, run_async=False):
        """
        Executa a command
        param: timeout: execution timeout
        param: run_async: do not wait for command completion
        """
        if not self.ip_address or self.ip_address == '0.0.0.0':
            raise Exception('Invalid IP Address')

        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd, timeout=timeout)
        except Exception:
            # Normally this is a timeout exception
            self.ssh_client = self.create_client()
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd, timeout=timeout)

        out = None
        err = None

        if not run_async:
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()

        return out, err

    def download_remote_file(self, remote_src, local_dst):
        """
        Downloads a remote file to a local destination
        param: local_src: local file path source
        param: remote_dst: remote file path destination
        """
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        dirname = os.path.dirname(local_dst)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)

        ftp_client = self.ssh_client.open_sftp()
        ftp_client.get(remote_src, local_dst)
        ftp_client.close()

    def upload_local_file(self, local_src, remote_dst):
        """
        Upload a local file to a rempote destination
        param: local_src: local file path source
        param: remote_dst: remote file path destination
        """
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        ftp_client = self.ssh_client.open_sftp()
        ftp_client.put(local_src, remote_dst)
        ftp_client.close()

    def upload_multiple_local_files(self, file_list):
        """
        upload multiple files with the same sftp connection
        param: file_list: list of tuples [(local_src, remote_dst),]
        """
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        ftp_client = self.ssh_client.open_sftp()
        for local_src, remote_dst in file_list:
            ftp_client.put(local_src, remote_dst)
        ftp_client.close()

    def upload_data_to_file(self, data, remote_dst):
        """
        upload data to a remote file
        param: data: string data
        param: remote_dst: remote file path destination
        """
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        ftp_client = self.ssh_client.open_sftp()

        with ftp_client.open(remote_dst, 'w') as f:
            f.write(data)

        ftp_client.close()
