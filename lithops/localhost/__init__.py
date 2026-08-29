from .v1.localhost import LocalhostHandlerV1
from .v2.localhost import LocalhostHandlerV2

# Callers that do not select a version explicitly get v2
LocalhostHandler = LocalhostHandlerV2

__all__ = [
    'LocalhostHandler',
    'LocalhostHandlerV1',
    'LocalhostHandlerV2',
]
