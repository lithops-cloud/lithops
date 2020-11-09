#
# Copyright Cloudlab URV 2020
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import json
import logging
from lithops.version import __version__
from lithops.utils import setup_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker

logger = logging.getLogger('lithops.worker')


def main(event, context):
    args = json.loads(event)
    os.environ['__LITHOPS_ACTIVATION_ID'] = context.request_id
    setup_logger(args['log_level'])
    if 'remote_invoker' in args:
        logger.info("Lithops v{} - Starting invoker".format(__version__))
        function_invoker(args)
    else:
        logger.info("Lithops v{} - Starting execution".format(__version__))
        function_handler(args)

    return {"Execution": "Finished"}


def extract_preinstalls(event, context):
    import sys
    import pkgutil

    print("Extracting preinstalled Python modules...")
    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta["preinstalls"] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta["python_ver"] = str(python_version[0]) + "." + str(python_version[1])
    print("Done!")
    return runtime_meta
