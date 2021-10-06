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
qemu-img resize ubuntu-20.04-server-cloudimg-amd64.img +7.5G
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
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get update'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-get install unzip redis-server python3-pip docker-ce docker-ce-cli containerd.io -y'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'pip3 install -U flask gevent lithops'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'rm -rf /var/lib/apt/lists/*'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'rm -rf /var/cache/apt/archives/*'
virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'apt-cache search linux-headers-generic'
printf "\n\n"


include_docker(){
    # Include docker image
    echo "-------------------------------------------"
    echo "--> Including docker image into the VM  <--"
    echo "-------------------------------------------"
    echo "Docker image: $DOCKER_IMAGE"
    echo ""

	apt-get install docker.io

    if [ "$DOCKER_PRUNE" == "prune" ]; then
      docker system prune -a -f
    fi

    docker pull $DOCKER_IMAGE
    
    sudo tar -cvf docker.tar /var/lib/docker > /dev/null 2>&1
    virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img  --run-command 'mkdir -p /tmp'
    virt-copy-in -a ubuntu-20.04-server-cloudimg-amd64.img docker.tar /tmp
    virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img --run-command 'tar -xvf /tmp/docker.tar -C /'
    virt-customize -a ubuntu-20.04-server-cloudimg-amd64.img --run-command 'rm -R /tmp'
    sudo rm docker.tar
    printf "\n\n"
}


while getopts "d:p:" opt
do
   case "$opt" in
      d ) DOCKER_IMAGE="$OPTARG";;
      p ) DOCKER_PRUNE="$OPTARG";;
   esac
done


if [ ! -z "$DOCKER_IMAGE" ]; then
     include_docker;
     FINAL_IMAGE=$3;
     if [ ! -z "$DOCKER_PRUNE" ]; then
        FINAL_IMAGE=$5;
     fi
else
     FINAL_IMAGE=$1;
fi


# Finished
echo "-------------------------------------------------------------------"
echo "--> Compressing image ubuntu-20.04-server-cloudimg-amd64.img    <--"
echo "-------------------------------------------------------------------"
echo "Final VM image: $FINAL_IMAGE"
echo ""
virt-sparsify ubuntu-20.04-server-cloudimg-amd64.img --compress $FINAL_IMAGE

#rm ubuntu-20.04-server-cloudimg-amd64.img
#kvm -net nic -net user -hda ubuntu-20.04-server-cloudimg-amd64.img -m 512

echo "----------------------------------------------"
echo "-->   Congratulations! VM Image Created    <--"
echo "----------------------------------------------"