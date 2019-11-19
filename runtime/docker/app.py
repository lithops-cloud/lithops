import sys
import json
import logging
from pywren_ibm_cloud.config import cloud_logging_config
from pywren_ibm_cloud.runtime.function_handler import function_handler

cloud_logging_config(logging.INFO)
logger = logging.getLogger('__main__')


if __name__ == "__main__":
    try:
        payload_file = sys.argv[1]
        with open(payload_file, "r") as f:
            json_payload = f.read()
        payload = json.loads(json_payload)
        function_handler(payload)
    except Exception as e:
        raise(e)
