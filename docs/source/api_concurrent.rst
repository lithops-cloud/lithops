Concurrent Futures API
======================

``lithops.concurrent.futures`` is a drop-in for Python's
`concurrent.futures <https://docs.python.org/3/library/concurrent.futures.html>`_
**Executor interface**. Swap the import and the same client keeps working:

.. code:: python

    # from concurrent.futures import ProcessPoolExecutor, as_completed, wait
    from lithops.concurrent.futures import ProcessPoolExecutor, as_completed, wait

    def same_client(executor):
        with executor:
            future = executor.submit(pow, 323, 1235)
            print(future.result())
            print(list(executor.map(abs, [-1, 2, -3])))

    same_client(ProcessPoolExecutor())

``ThreadPoolExecutor`` is provided under the same name for import compatibility;
both names run tasks on Lithops workers.

This is separate from the :doc:`Core API <api_futures>` (``lithops.FunctionExecutor``),
whose ``map()`` returns futures, which has ``call_async()`` instead of ``submit()``,
and whose ``wait()`` is a method with Lithops-specific ``return_when`` values.


Implemented standard-library surface
------------------------------------

The module exports the names application code actually uses:

* **Executor** — ``submit()``, eager ``map()`` (results, not futures),
  ``shutdown(wait=True, *, cancel_futures=False)``, context manager
* **ProcessPoolExecutor** / **ThreadPoolExecutor** — Lithops-backed pools
* **Future** — subclass of ``concurrent.futures.Future``:
  ``result()``, ``exception()``, ``done()``, ``running()``, ``cancel()``,
  ``cancelled()``, ``add_done_callback()``
* **wait** / **as_completed** — same contract and constants
  (``FIRST_COMPLETED``, ``FIRST_EXCEPTION``, ``ALL_COMPLETED``)
* **Exceptions** — ``CancelledError``, ``TimeoutError``, ``BrokenExecutor``,
  ``InvalidStateError``

``InterpreterPoolExecutor`` (Python 3.14) is not implemented: Lithops has no
isolated-interpreter workers.

``map()`` submits one Lithops ``map()`` job for the whole iterable, not one
``submit()`` per item. Callables travel through a trampoline, so builtins such
as ``abs`` and ``pow`` work. Its ``chunksize`` is how many items each Lithops
worker takes, which is what it means for the standard ``ProcessPoolExecutor``
too; left unset, the ``chunksize`` of the Lithops configuration applies rather
than the standard library default of one item per worker.

.. code:: python

    from lithops.concurrent.futures import FunctionExecutor, as_completed

    def load(url):
        return url, len(url)

    with FunctionExecutor() as executor:
        futures = {executor.submit(load, url): url for url in ('a', 'bb', 'ccc')}
        for future in as_completed(futures):
            url, size = future.result()
            print(url, size)

Mode-specific subclasses ``LocalhostExecutor``, ``ServerlessExecutor`` and
``StandaloneExecutor`` pin the Lithops execution mode the same way the Core API
executors do. You can wrap an existing Core API executor::

    import lithops
    from lithops.concurrent.futures import FunctionExecutor

    fexec = lithops.FunctionExecutor()
    with FunctionExecutor(executor=fexec) as executor:
        print(executor.submit(pow, 2, 8).result())


Runtime differences
-------------------

The *API* matches ``concurrent.futures``. The *runtime* is Lithops:

* Workers are Lithops activations, not local threads or ``multiprocessing`` processes.
  ``mp_context``, ``max_tasks_per_child``, and ``thread_name_prefix`` are ignored.
* ``initializer`` / ``initargs`` are not supported (workers are ephemeral) and raise
  ``NotImplementedError`` if provided.
* ``cancel()`` cannot stop a job Lithops has already dispatched. ``submit()`` marks
  the future as running immediately, so ``cancel()`` returns ``False``, and
  ``shutdown(cancel_futures=True)`` therefore still waits the calls out.
* Lithops job options (``runtime_memory``, ``extra_env``, ``execution_timeout``,
  ``include_modules``, ``exclude_modules``) are set on the executor. Keyword
  arguments to ``submit(fn, *args, **kwargs)`` are passed to ``fn``.
* Each ``Future`` also exposes ``lithops_future`` and ``stats``.
* A call Lithops loses track of raises ``RuntimeError`` rather than handing
  back a silent ``None``. It fails that one future; the executor stays usable.
* ``RetryingFunctionExecutor`` cannot be wrapped. Its retries are driven from
  its own ``wait()``, which this adapter never calls, so wrapping it would
  quietly give you no retries at all. Wrap the ``FunctionExecutor`` it holds.

Completion is tracked by the Lithops job monitor, the same one the native
``wait()`` uses: one batched poll per round for the whole job rather than one
status read per call. Results are downloaded off the tracking thread, so a
slow object does not hold up the futures behind it, and ``done()`` never
blocks on storage.

.. automodule:: lithops.concurrent.futures
   :members: FunctionExecutor, LocalhostExecutor, ServerlessExecutor,
             StandaloneExecutor, ProcessPoolExecutor, ThreadPoolExecutor,
             Future, wait, as_completed
   :show-inheritance:
