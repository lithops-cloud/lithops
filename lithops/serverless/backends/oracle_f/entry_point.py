import os
import json
import logging
from lithops.version import __version__
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata
import sys
from fdk import response

logger = logging.getLogger(__name__)

async def handler(ctx, data=None):

    if data:
        event = data.read().decode('utf-8')
    else:
        event = ''
    args = json.loads(event)

    os.environ['__LITHOPS_ACTIVATION_ID'] = ctx.CallID()
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

    return response.Response(ctx, response_data=json.dumps({"Execution": "Finished"}))
