#!/bin/sh
echo "Installing PyWren for IBM Cloud Functions..."
wget --no-check-certificate 'https://github.com/pywren/pywren-ibm-cloud/archive/master.zip' -O pywren_ibm_cloud.zip 2> /dev/null
unzip  pywren_ibm_cloud.zip > /dev/null
cd pywren-ibm-cloud-master/pywren; pip install -U . > /dev/null
echo "done!"