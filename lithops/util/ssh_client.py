import paramiko
import logging
import os

logger = logging.getLogger(__name__)


class SSHClient():

    def __init__(self, ip_address, ssh_credentials):
        self.ip_address = ip_address
        self.ssh_credentials = ssh_credentials
        self.ssh_client = None

        if 'key_filename' in self.ssh_credentials and \
           self.ssh_credentials['key_filename'] and \
           '~' in self.ssh_credentials['key_filename']:
            fpath = os.path.expanduser(self.ssh_credentials['key_filename'])
            self.ssh_credentials['key_filename'] = fpath

    def close(self):
        """
        Closes the SSH client connection
        """
        self.ssh_client.close()
        self.ssh_client = None

    def create_client(self, timeout=2):
        """
        Crate the SSH client connection
        """
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(self.ip_address, **self.ssh_credentials,
                                timeout=timeout, banner_timeout=200)

        logger.debug("{} ssh client created".format(self.ip_address))

        return self.ssh_client

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
        except Exception as e:
            # Normally this is a timeout exception
            self.ssh_client = self.create_client()
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd, timeout=timeout)

        out = None
        if not run_async:
            out = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

        return out

    def upload_local_file(self, local_src, remote_dst):
        """
        Upload local file to a rempote destination
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
