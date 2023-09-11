# (C) Copyright Cloudlab URV 2023
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
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata
import io

logger = logging.getLogger(__name__)


def handler(ctx, data: io.BytesIO = None):

    try:
        args = json.loads(data.getvalue())
    except (Exception, ValueError) as ex:
        print(str(ex))

    call_id = ctx.CallID()

    os.environ['__LITHOPS_ACTIVATION_ID'] = call_id
    os.environ['__LITHOPS_BACKEND'] = 'Oracle Function Compute'

    if 'get_metadata' in args:
        logger.debug(f"Lithops v{__version__} - Generating metadata")
        metadata = get_runtime_metadata()
        return metadata
    elif 'remote_invoker' in args:
        logger.debug(f"Lithops v{__version__} - Starting Oracle Function Compute invoker")
        function_invoker(args)
    else:
        logger.debug(f"Lithops v{__version__} - Starting Oracle Function Compute execution")
        function_handler(args)

    return call_id
