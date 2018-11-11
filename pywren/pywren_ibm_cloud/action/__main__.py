import logging
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.action.wrenhandler import ibm_cloud_function_handler

logger = logging.getLogger('__main__')
wrenlogging.ow_config(logging.DEBUG)


def main(args):
    logger.info("Starting IBM Cloud Function execution")
    ibm_cloud_function_handler(args)
    return {"greeting": "Finished"}
