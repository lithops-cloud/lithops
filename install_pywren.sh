#!/bin/sh
if [ -z "$1" ]
then
    # If no version provided, get last release
    RELEASE=`wget -q --no-check-certificate https://api.github.com/repos/pywren/pywren-ibm-cloud/releases/latest -O - | grep '"tag_name":' |  sed -E 's/.*"([^"]+)".*/\1/'`
else
    RELEASE=$1
fi

echo "Installing PyWren for IBM Cloud Functions - Release $RELEASE ..."
rm -rf pywren-ibm-cloud* > /dev/null
wget --no-check-certificate 'https://github.com/pywren/pywren-ibm-cloud/archive/'$RELEASE'.zip' -O pywren-ibm-cloud.zip 2> /dev/null
unzip  pywren-ibm-cloud.zip > /dev/null
mv pywren-ibm-cloud-$RELEASE pywren-ibm-cloud
cd pywren-ibm-cloud; pip install -U . > /dev/null
echo "done!"