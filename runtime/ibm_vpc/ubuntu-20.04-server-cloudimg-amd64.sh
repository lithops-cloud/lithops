# Prepare local machine for the process
echo "--------------------------------------------"
echo "-->        Updating local machine        <--"
echo "--------------------------------------------"
sudo apt-get update
sudo apt-get install libguestfs-tools expect -y
printf "\n\n"

# Download base image and show image information and partitions
echo "----------------------------------------------------------"
echo "--> Downloading ubuntu-20.04-server-cloudimg-amd64.img <--"
echo "----------------------------------------------------------"
curl -O https://cloud-images.ubuntu.com/releases/focal/release/ubuntu-20.04-server-cloudimg-amd64.img
qemu-img info ubuntu-20.04-server-cloudimg-amd64.img
virt-df -h -a ubuntu-20.04-server-cloudimg-amd64.img
printf "\n\n"

# Resize /dev/sda1 Partition
echo "-------------------------------------------------------"
echo "--> Resizing ubuntu-20.04-server-cloudimg-amd64.img <--"
echo "-------------------------------------------------------"
cp ubuntu-20.04-server-cloudimg-amd64.img ubuntu-20.04-server-cloudimg-amd64-orig.img
qemu-img resize ubuntu-20.04-server-cloudimg-amd64.img +5G
virt-resize --expand /dev/sda1 ubuntu-20.04-server-cloudimg-amd64-orig.img ubuntu-20.04-server-cloudimg-amd64.img
rm ubuntu-20.04-server-cloudimg-amd64-orig.img
virt-filesystems --long -h --all -a ubuntu-20.04-server-cloudimg-amd64.img
printf "\n\n"

# Fix partitions
echo "---------------------------------------"
echo "-->        Fixing partitions        <--"
echo "---------------------------------------"

/usr/bin/expect <<EOD
    set timeout -1
    spawn virt-rescue ubuntu-20.04-server-cloudimg-amd64.img
    expect "*<rescue>*"
    send -- "mkdir /mnt\r"
    expect "*<rescue>*"
    send -- "mount /dev/sda3 /mnt\r"
    expect "*<rescue>*"
    send -- "mount --bind /dev /mnt/dev\r"
    expect "*<rescue>*"
    send -- "mount --bind /proc /mnt/proc\r"
    expect "*<rescue>*"
    send -- "mount --bind /sys /mnt/sys\r"
    expect "*<rescue>*"
    send -- "chroot /mnt\r"
    expect "*<rescue>*"
    send -- "grub-install /dev/sda\r"
    expect "*<rescue>*"
    send -- "exit\r"
    expect "*<rescue>*"
    send -- "exit\r"
    expect eof
EOD
printf "\n\n\n"


# Install Lithops packages
echo "--------------------------------------------"
echo "-->   Installing lithops dependencies    <--"
echo "--------------------------------------------"
sleep 5
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'rm /var/lib/apt/lists/* -vfR ' 
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get clean' 
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get update'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install unzip python3-pip apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get update'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install unzip python3-pip docker-ce docker-ce-cli containerd.io -y'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'pip3 install -U flask gevent lithops'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'rm -rf /var/lib/apt/lists/*'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'rm -rf /var/cache/apt/archives/*'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-cache search linux-headers-generic'
printf "\n\n"

# Finished
echo "-------------------------------------------------------------------"
echo "--> Compressing image ubuntu-20.04-server-cloudimg-amd64.img    <--"
echo "-------------------------------------------------------------------"
virt-sparsify ubuntu-20.04-server-cloudimg-amd64.img --compress ubuntu2004srv.qcow2

#rm ubuntu-20.04-server-cloudimg-amd64.img
#kvm -net snap3 -net user -hda ubuntu-20.04-server-cloudimg-amd64.img -m 512

echo "---------------------------------------------------------------"
echo "-->   Congratulations! Image ubuntu2004srv.qcow2 Created    <--"
echo "---------------------------------------------------------------"