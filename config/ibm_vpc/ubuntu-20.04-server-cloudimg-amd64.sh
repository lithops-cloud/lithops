curl -O https://cloud-images.ubuntu.com/releases/focal/release/ubuntu-20.04-server-cloudimg-amd64.img
sudo apt-get update
sudo apt-get upgrade
sudo apt-get install libguestfs-tools expect
sudo chmod 0644 /boot/vmlinuz*
virt-df -h -a ubuntu-20.04-server-cloudimg-amd64.img

curl -O https://cloud-images.ubuntu.com/releases/focal/release/ubuntu-20.04-server-cloudimg-amd64.img
qemu-img info ubuntu-20.04-server-cloudimg-amd64.img
qemu-img resize ubuntu-20.04-server-cloudimg-amd64.img +3G
cp ubuntu-20.04-server-cloudimg-amd64.img ubuntu-20.04-server-cloudimg-amd64-orig.img
virt-resize --expand /dev/sda1 ubuntu-20.04-server-cloudimg-amd64-orig.img ubuntu-20.04-server-cloudimg-amd64.img
qemu-img info ubuntu-20.04-server-cloudimg-amd64.img
virt-filesystems --long -h --all -a ubuntu-20.04-server-cloudimg-amd64.img

echo "Fixing partitions"
/usr/bin/expect <<EOD
spawn virt-rescue ubuntu-20.04-server-cloudimg-amd64.img
match_max 100000
expect "*<rescue>*"
send -- "mkdir /mnt\r"
send -- "mount /dev/sda3 /mnt\r"
send -- "mount --bind /dev /mnt/dev\r"
send -- "mount --bind /proc /mnt/proc\r"
send -- "mount --bind /sys /mnt/sys\r"
send -- "chroot /mnt\r"
send -- "grub-install /dev/sda\r"
send -- "exit\r"
expect eof
EOD

virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'mkdir -p /tmp/lithops'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'sudo rm -R -f /var/lib/apt/lists/* -vf' 
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get clean'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get update >> /tmp/lithops/proxy.log'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install unzip python3-pip -y >> /tmp/lithops/proxy.log'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'pip3 install flask gevent pika==0.13.1 ibm-vpc>=0.4.0 namegenerator ibm-cos-sdk requests paramiko python-dateutil>> /tmp/lithops/proxy.log'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install apt-transport-https ca-certificates curl gnupg-agent software-properties-common -y'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add - > /dev/null 2>&1 '
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"' 
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install docker-ce docker-ce-cli containerd.io -y'

virt-df -h -a ubuntu-20.04-server-cloudimg-amd64.img
mv ubuntu-20.04-server-cloudimg-amd64.img ubuntu2004srv.qcow2
