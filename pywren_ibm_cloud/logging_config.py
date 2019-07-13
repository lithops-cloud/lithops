import logging.config


def default_logging_config(log_level='INFO'):
    if log_level == 'DEBUG_BOTO3':
        log_level = 'DEBUG'
        logging.getLogger('ibm_boto3').setLevel(logging.DEBUG)
        logging.getLogger('ibm_botocore').setLevel(logging.DEBUG)

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': log_level,
                'class': 'logging.StreamHandler',
                'formatter': 'standard'
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': log_level,
                'propagate': True
            }
        }
    })


def ibm_cf_logging_config(log_level='INFO'):
    if log_level == 'DEBUG_BOTO3':
        log_level = 'DEBUG'
        logging.getLogger('ibm_boto3').setLevel(logging.DEBUG)
        logging.getLogger('ibm_botocore').setLevel(logging.DEBUG)

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '[%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': log_level,
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'stream': 'ext://sys.stdout'
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': log_level,
                'propagate': True
            }
        }
    })
