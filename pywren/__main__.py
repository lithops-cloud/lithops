from __future__ import print_function
from pywren_ibm_cloud.wrenhandler import ibm_cloud_function_handler
import logging
from pywren_ibm_cloud import wrenlogging

logger = logging.getLogger('pywren')
wrenlogging.ow_config(logging.INFO)


def main(args):
    logger.info("Starting IBM Cloud Function execution")
    ibm_cloud_function_handler(args)
    return {"greeting": "Finished"}