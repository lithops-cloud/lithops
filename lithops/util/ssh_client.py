import paramiko
import logging

logger = logging.getLogger(__name__)


class SSHClient():

    def __init__(self, ssh_credentials):
        self.ssh_credentials = ssh_credentials
        self.ssh_client = None

    def create_client(self, ip_address, timeout=None):
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(ip_address, **self.ssh_credentials,
                                timeout=timeout, banner_timeout=200)

        logger.debug("{} ssh client created".format(ip_address))

        return self.ssh_client

    def run_remote_command(self, ip_address, cmd, timeout=None, background=False):
        if self.ssh_client is None:
            self.ssh_client = self.create_client(ip_address, timeout)

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd)
            logger.debug("ssh executed against {} ".format(ip_address))
        except Exception as e:
            self.ssh_client = self.create_client(ip_address, timeout)
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd)

        out = None
        if not background:
            out = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            logger.debug("{}  - {}".format(ip_address, out))

        return out

    def upload_local_file(self, ip_address, local_src, remote_dst, timeout=None):
        if self.ssh_client is None:
            self.ssh_client = self.create_client(ip_address, timeout)

        ftp_client = self.ssh_client.open_sftp()
        ftp_client.put(local_src, remote_dst)
        ftp_client.close()

    def upload_data_to_file(self, ip_address, data, remote_dst, timeout=None):
        if self.ssh_client is None:
            self.ssh_client = self.create_client(ip_address, timeout)

        ftp_client = self.ssh_client.open_sftp()

        with ftp_client.open(remote_dst, 'w') as f:
            f.write(data)

        ftp_client.close()
