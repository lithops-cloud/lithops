from lithops.executors import FunctionExecutor
from lithops.executors import LocalhostExecutor
from lithops.executors import ServerlessExecutor
from lithops.executors import StandaloneExecutor
from lithops.storage import Storage
from lithops.version import __version__


def function_executor(mode=None, config=None, backend=None, storage=None,
                      runtime=None, runtime_memory=None, workers=None,
                      rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Generic function executor
    """
    print("function_executor() is deprecated and will be removed in future releases")
    return FunctionExecutor(
        type=type,
        mode=mode,
        config=config,
        runtime=runtime,
        runtime_memory=runtime_memory,
        workers=workers,
        backend=backend,
        storage=storage,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def local_executor(config=None, workers=None,
                   storage_backend=None,
                   rabbitmq_monitor=None,
                   log_level=None):
    """
    Localhost function executor
    """
    print("local_executor() is deprecated and will be removed in future releases")
    return LocalhostExecutor(
        config=config, workers=workers,
        storage=storage_backend,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )
