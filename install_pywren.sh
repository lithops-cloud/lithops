#!/bin/sh
LAST_RELEASE=`wget -q --no-check-certificate https://api.github.com/repos/pywren/pywren-ibm-cloud/releases/latest -O - | grep '"tag_name":' |  sed -E 's/.*"([^"]+)".*/\1/'`
echo "Installing PyWren for IBM Cloud Functions - Release $LAST_RELEASE ..."
rm -rf pywren-ibm-cloud* > /dev/null
wget --no-check-certificate 'https://github.com/pywren/pywren-ibm-cloud/archive/'$LAST_RELEASE'.zip' -O pywren-ibm-cloud.zip 2> /dev/null
unzip  pywren-ibm-cloud.zip > /dev/null
mv pywren-ibm-cloud-$LAST_RELEASE pywren-ibm-cloud
cd pywren-ibm-cloud/pywren; pip install -U . > /dev/null
echo "done!"