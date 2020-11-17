import requests
import logging


logger = logging.getLogger(__name__)


class PrometheusExporter():

    def __init__(self, active, prometheus_config):
        """ Prometheus exporter for sending metrics to an API Gateway"""
        self.active = active
        self.apigateway = prometheus_config.get('apigateway')

    def send_metric(self, name, value, job_key, **labels):
        """Send a metric to prometheus"""

        if self.active and self.apigateway:
            dim = 'job/lithops/instance/{}'.format(job_key)
            for label in labels:
                dim += '/%s/%s' % (label, labels[label])
            url = '/'.join([self.apigateway, 'metrics', dim])
            logger.info('Sending metric "{} {}" to {}'.format(name, value, url))
            requests.post(url, data='%s %s\n' % (name, value))
