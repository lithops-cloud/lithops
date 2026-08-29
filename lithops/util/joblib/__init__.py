from joblib.parallel import register_parallel_backend


def register_lithops():
    """Register Lithops Backend to be called with parallel_backend("lithops")."""
    from lithops.util.joblib.lithops_backend import LithopsBackend
    register_parallel_backend("lithops", LithopsBackend)


__all__ = ["register_lithops"]
