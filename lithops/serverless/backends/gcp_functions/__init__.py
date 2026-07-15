from lithops import _grpc_env  # noqa: F401

from .gcp_functions import GCPFunctionsBackend as ServerlessBackend

__all__ = ['ServerlessBackend']
