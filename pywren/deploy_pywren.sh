cat action_files.lst | zip -@ -FSr ibmcf_pywren.zip -x "*__pycache__*"

# Runtimes
bx wsk action update pywren_3.6 --kind python-jessie:3 -m 512 -t 600000 ibmcf_pywren.zip