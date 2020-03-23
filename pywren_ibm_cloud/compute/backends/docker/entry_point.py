import sys
import json
import pkgutil
import logging
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.config import cloud_logging_config
from pywren_ibm_cloud.function import function_handler

cloud_logging_config(logging.INFO)
logger = logging.getLogger('__main__')


if __name__ == "__main__":

    cmd = sys.argv[1]

    if cmd == 'run':
        try:
            payload_file = sys.argv[2]
            with open(payload_file, "r") as f:
                json_payload = f.read()
            payload = json.loads(json_payload)
            function_handler(payload)
        except Exception as e:
            raise(e)
    elif cmd == 'metadata':
        runtime_meta = dict()
        mods = list(pkgutil.iter_modules())
        runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
        runtime_meta["python_ver"] = version_str(sys.version_info)
        print(json.dumps(runtime_meta))
    else:
        raise ValueError("Command not valid: {}", cmd)
