from .v1.localhost import LocalhostHandlerV1
from .v2.localhost import LocalhostHandlerV2

# Set the default localhost handler
LocalhostHandler = LocalhostHandlerV2

__all__ = [
    'LocalhostHandlerV1',
    'LocalhostHandlerV2'
]
