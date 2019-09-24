import sys
import os
import flask
import logging
import pkgutil
from pywren_ibm_cloud.config import cloud_logging_config
from pywren_ibm_cloud.runtime.function_handler import function_handler

cloud_logging_config(logging.INFO)
logger = logging.getLogger('__main__')


proxy = flask.Flask(__name__)


@proxy.route('/', methods=['POST'])
def run():
    def error():
        response = flask.jsonify({'error': 'The action did not receive a dictionary as an argument.'})
        response.status_code = 404
        return complete(response)

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error()

    logger.info("Starting knative Function execution")
    function_handler(message)
    result = {"Execution": "Finished"}
    response = flask.jsonify(result)
    response.status_code = 200

    return complete(response)


@proxy.route('/preinstalls', methods=['GET', 'POST'])
def preinstalls_task():
    logger.info("Extracting preinstalled Python modules...")

    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta['python_ver'] = str(python_version[0])+"."+str(python_version[1])
    response = flask.jsonify(runtime_meta)
    response.status_code = 200
    logger.info("Done!")

    return complete(response)


def complete(response):
    # Add sentinel to stdout/stderr
    sys.stdout.write('%s\n' % 'XXX_THE_END_OF_AN_ACTIVATION_XXX')
    sys.stdout.flush()

    return response


def main():
    port = int(os.getenv('PORT', 8080))
    proxy.run(debug=True, host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()
