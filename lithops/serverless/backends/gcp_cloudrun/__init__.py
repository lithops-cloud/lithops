from lithops import _grpc_env  # noqa: F401

from .cloudrun import GCPCloudRunBackend as ServerlessBackend

__all__ = ['ServerlessBackend']
