from lithops import _grpc_env  # noqa: F401

from .gcp_compute_engine import GCPComputeEngineBackend as StandaloneBackend

__all__ = ['StandaloneBackend']
