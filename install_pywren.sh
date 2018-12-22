#!/bin/sh
echo "Installing PyWren for IBM Cloud Functions..."
rm -rf pywren-ibm-cloud.zip > /dev/null
wget --no-check-certificate 'https://github.com/pywren/pywren-ibm-cloud/archive/master.zip' -O pywren-ibm-cloud.zip 2> /dev/null
rm -rf pywren-ibm-cloud-master; unzip  pywren-ibm-cloud.zip > /dev/null
cd pywren-ibm-cloud-master/pywren; pip install -U . > /dev/null
echo "done!"