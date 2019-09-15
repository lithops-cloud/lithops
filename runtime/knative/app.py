import logging
import json
import sys
import pkgutil
import os
from pywren_ibm_cloud.runtime.function_handler.handler import function_handler
from flask import Flask, request, jsonify

logger = logging.getLogger('__main__')

app = Flask(__name__)

@app.route('/', methods=['POST'])
def pywren_task():
    print(request.data)
    logger.info("Starting Knative execution")
    json_dict = json.loads(request.data)
    function_handler(json_dict)
    return jsonify({'id': 'none'})

@app.route('/preinstalls', methods=['POST'])
def preinstalls_task():
    logger.info("Starting Knative execution")
    print("Extracting preinstalled Python modules...")
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta['python_ver'] = str(python_version[0])+"."+str(python_version[1])
    return jsonify(runtime_meta)


if __name__ == "__main__":
    app.run(debug=True,host='0.0.0.0',port=int(os.environ.get('PORT', 8080)))
