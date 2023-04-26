import os
import json
import logging
import uuid
from lithops.version import __version__
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handler(context, data=None):
    
    logger.info("Handler started %s",sys.path)    
    if data:
        event = data.read().decode('utf-8')
    else:
        event = ''
    args = json.loads(event)
    logger.info("Args: %s", event)

        
    os.environ['__LITHOPS_ACTIVATION_ID'] = str(uuid.uuid4())
    os.environ['__LITHOPS_BACKEND'] = 'Oracle Function Compute'

   

    if 'get_metadata' in args:
        logger.info(f"Lithops v{__version__} - Generating metadata")
        metadata = get_runtime_metadata()
        logger.info("get_metadata function")

        logger.info("Metadata: %s", metadata)
        logger.info("Lithops version %s", metadata['lithops_version'])
        return metadata
    elif 'remote_invoker' in args:
        logger.info(f"Lithops v{__version__} - Starting Oracle Function Compute invoker")
        function_invoker(args)
    else:
        logger.info(f"Lithops v{__version__} - Starting Oracle Function Compute execution")
        function_handler(args)

    
    return {"Execution": "Finished"}
