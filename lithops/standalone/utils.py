import paramiko
import logging

logging.getLogger('paramiko').setLevel(logging.CRITICAL)


class SSHClient():

    def __init__(self, ssh_credentials):
        self.ssh_clients = {}
        self.ssh_credentials = ssh_credentials

    def create_client(self, ip_address, timeout=None):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(ip_address, **self.ssh_credentials, timeout=timeout)

        return ssh_client

    def run_remote_command(self, ip_address, cmd, timeout=None, background=False):
        if ip_address not in self.ssh_clients:
            ssh_client = self.create_client(ip_address, timeout)
        else:
            ssh_client = self.ssh_clients[ip_address]

        try:
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
        except Exception:
            ssh_client = self._create_client(ip_address, timeout=timeout, force=True)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)

        out = None
        if not background:
            out = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

            if error:
                raise Exception('There was an error running remote ssh command: {}'.format(error))

        return out

    def upload_local_file(self, ip_address, local_src, remote_dst, timeout=None):
        if ip_address not in self.ssh_clients:
            ssh_client = self.create_client(ip_address, timeout)
        else:
            ssh_client = self.ssh_clients[ip_address]
        ftp_client = ssh_client.open_sftp()
        ftp_client.put(local_src, remote_dst)
        ftp_client.close()

    def upload_data_to_file(self, ip_address, data, remote_dst, timeout=None):
        if ip_address not in self.ssh_clients:
            ssh_client = self.create_client(ip_address, timeout)
        else:
            ssh_client = self.ssh_clients[ip_address]
        ftp_client = ssh_client.open_sftp()

        with ftp_client.open(remote_dst, 'w') as f:
            f.write(data)

        ftp_client.close()
