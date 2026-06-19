# Prepare local machine for the process
echo "--------------------------------------------"
echo "-->        Updating local machine        <--"
echo "--------------------------------------------"
sudo apt-get update
sudo apt-get install libguestfs-tools expect -y
printf "\n\n"

BASE_IMAGE="ubuntu-24.04-server-cloudimg-amd64.img"
BASE_URL="https://cloud-images.ubuntu.com/releases/noble/release/${BASE_IMAGE}"

# Download base image and show image information and partitions
echo "----------------------------------------------------------"
echo "--> Downloading ${BASE_IMAGE} <--"
echo "----------------------------------------------------------"
curl -L -O "${BASE_URL}"
qemu-img info "${BASE_IMAGE}"
virt-df -h -a "${BASE_IMAGE}"
printf "\n\n"

# Resize root partition
echo "-------------------------------------------------------"
echo "--> Resizing ${BASE_IMAGE} <--"
echo "-------------------------------------------------------"
cp "${BASE_IMAGE}" "${BASE_IMAGE%.img}-orig.img"
qemu-img resize "${BASE_IMAGE}" +7.5G
virt-resize --expand /dev/sda1 "${BASE_IMAGE%.img}-orig.img" "${BASE_IMAGE}"
rm "${BASE_IMAGE%.img}-orig.img"
virt-filesystems --long -h --all -a "${BASE_IMAGE}"
printf "\n\n"

# Fix partitions
echo "---------------------------------------"
echo "-->        Fixing partitions        <--"
echo "---------------------------------------"

/usr/bin/expect <<EOD
    set timeout -1
    spawn virt-rescue ${BASE_IMAGE}
    expect "*<rescue>*"
    send -- "mkdir /mnt\r"
    expect "*<rescue>*"
    send -- "mount /dev/sda1 /mnt\r"
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
virt-customize -a "${BASE_IMAGE}"  --run-command 'rm /var/lib/apt/lists/* -vfR '
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-get clean'
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-get update'
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-get install apt-transport-https ca-certificates curl software-properties-common gnupg-agent -y'
virt-customize -a "${BASE_IMAGE}"  --run-command 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg'
virt-customize -a "${BASE_IMAGE}"  --run-command 'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list'
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-get update'
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-get install unzip redis-server python3-pip docker-ce docker-ce-cli containerd.io -y'
virt-customize -a "${BASE_IMAGE}"  --run-command 'pip3 install -U flask gevent lithops'
virt-customize -a "${BASE_IMAGE}"  --run-command 'rm -rf /var/lib/apt/lists/*'
virt-customize -a "${BASE_IMAGE}"  --run-command 'rm -rf /var/cache/apt/archives/*'
virt-customize -a "${BASE_IMAGE}"  --run-command 'apt-cache search linux-headers-generic'
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
    virt-customize -a "${BASE_IMAGE}"  --run-command 'mkdir -p /tmp'
    virt-copy-in -a "${BASE_IMAGE}" docker.tar /tmp
    virt-customize -a "${BASE_IMAGE}" --run-command 'tar -xvf /tmp/docker.tar -C /'
    virt-customize -a "${BASE_IMAGE}" --run-command 'rm -R /tmp'
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
echo "--> Compressing image ${BASE_IMAGE}    <--"
echo "-------------------------------------------------------------------"
echo "Final VM image: $FINAL_IMAGE"
echo ""
virt-sparsify "${BASE_IMAGE}" --compress "$FINAL_IMAGE"

echo "----------------------------------------------"
echo "-->   Congratulations! VM Image Created    <--"
echo "----------------------------------------------"
