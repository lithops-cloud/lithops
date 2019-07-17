import logging
import json
from pywren_ibm_cloud.logging_config import ibm_cf_logging_config
from pywren_ibm_cloud.action.handler import function_handler

ibm_cf_logging_config(logging.INFO)
logger = logging.getLogger('__main__')

import os

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/', methods=['POST'])
def pywren_task():
    print(request.data)
    logger.info("Starting Knative execution")
    json_dict = json.loads(request.data)
    function_handler(json_dict)
    return jsonify({'id': 'none'})

if __name__ == "__main__":
    app.run(debug=True,host='0.0.0.0',port=int(os.environ.get('PORT', 8080)))
