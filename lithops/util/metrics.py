import logging
import os
from typing import Any, Dict, Optional, Sequence, Tuple

import requests

logger = logging.getLogger(__name__)

_DEFAULT_INSTANCE = 'lithops'


class PrometheusExporter:
    """
    Pushes Lithops metrics to a Prometheus pushgateway sitting behind an API
    Gateway. Does nothing unless it is enabled and a gateway is configured
    """

    def __init__(self, enabled: bool, config: Optional[Dict[str, Any]]):
        self.enabled = enabled
        self.apigateway = config.get('apigateway') if config else None
        self.job = 'lithops'
        session_id = os.environ.get('__LITHOPS_SESSION_ID', _DEFAULT_INSTANCE)
        self.instance = session_id.split('-')[0]

    def send_metric(
        self,
        name: str,
        value: Any,
        type: str,
        labels: Sequence[Tuple[str, Any]],
    ) -> None:
        """
        Sends a single metric, with the labels appended to the pushgateway
        grouping key. Errors are logged and swallowed: metrics are optional
        """
        if not (self.enabled and self.apigateway):
            return

        dim = f'job/{self.job}/instance/{self.instance}'
        for key, val in labels:
            dim += f'/{key}/{val}'
        url = '/'.join([self.apigateway, 'metrics', dim])
        logger.debug(f'Sending metric "{name} {value} ({type})" to {url}')

        try:
            requests.post(url, data=f'# TYPE {name} {type}\n{name} {value}\n')
        except Exception as exc:
            logger.error(exc)
