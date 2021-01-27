import paramiko
import logging

logger = logging.getLogger(__name__)


class SSHClient():

    def __init__(self, ip_address, ssh_credentials):
        self.ip_address = ip_address
        self.ssh_credentials = ssh_credentials
        self.ssh_client = None

    def close(self):
        self.ssh_client.close()

    def create_client(self, timeout=None):
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(self.ip_address, **self.ssh_credentials,
                                timeout=timeout, banner_timeout=200)

        logger.debug("{} ssh client created".format(self.ip_address))

        return self.ssh_client

    def run_remote_command(self, cmd, timeout=None, run_async=False):
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd, timeout=timeout)
        except Exception as e:
            self.ssh_client = self.create_client()
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd, timeout=timeout)

        out = None
        if not run_async:
            out = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

        return out

    def upload_local_file(self, local_src, remote_dst):
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        ftp_client = self.ssh_client.open_sftp()
        ftp_client.put(local_src, remote_dst)
        ftp_client.close()

    def upload_data_to_file(self, data, remote_dst):
        if self.ssh_client is None:
            self.ssh_client = self.create_client()

        ftp_client = self.ssh_client.open_sftp()

        with ftp_client.open(remote_dst, 'w') as f:
            f.write(data)

        ftp_client.close()
