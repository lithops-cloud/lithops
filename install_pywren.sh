#!/bin/sh
#Command: curl -fsSL "https://docs.google.com/uc?export=download&id=10PBhuaPU5YZBpZXm-6I7c12L2qpa40C4" | sh
echo "Installing PyWren for IBM Cloud Functions..."
wget --no-check-certificate 'https://docs.google.com/uc?export=download&id=1M4UmpVoEjdyZ3zX9_IlwnVT2HxB0yzRQ' -O pywren_ibm_cloud.tar.gz 2> /dev/null
tar -xvzf pywren_ibm_cloud.tar.gz > /dev/null
cd pywren; pip install -U . > /dev/null
echo "done!"
