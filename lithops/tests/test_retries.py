import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lithops import FunctionExecutor
from lithops import RetryingFunctionExecutor
from lithops.retries import RetryingFuture
from lithops.utils import FuturesList
from lithops.wait import ALWAYS, ANY_COMPLETED


def run_test(function, input, retries, timeout=5):
    fexec = FunctionExecutor(config=pytest.lithops_config)
    with RetryingFunctionExecutor(fexec) as executor:
        futures = executor.map(
            function,
            input,
            timeout=timeout,
            retries=retries,
        )
        done, pending = executor.wait(futures, throw_except=False)
        assert len(pending) == 0
    outputs = set(f.result() for f in done)
    return outputs


# fmt: off
@pytest.mark.parametrize(
    "timing_map, n_tasks, retries",
    [
        # no failures
        ({}, 3, 2),
        # first invocation fails
        ({0: [-1], 1: [-1], 2: [-1]}, 3, 2),
        # first two invocations fail
        ({0: [-1, -1], 1: [-1, -1], 2: [-1, -1]}, 3, 2),
        # first input sleeps once
        ({0: [20]}, 3, 2),
    ],
)
# fmt: on
def test_success(tmp_path, timing_map, n_tasks, retries):
    def partial_map_function(x):
        return deterministic_failure(tmp_path, timing_map, x)

    outputs = run_test(
        function=partial_map_function,
        input=range(n_tasks),
        retries=retries,
    )

    assert outputs == set(range(n_tasks))

    check_invocation_counts(tmp_path, timing_map, n_tasks, retries)


# fmt: off
@pytest.mark.parametrize(
    "timing_map, n_tasks, retries",
    [
        # too many failures
        ({0: [-1], 1: [-1], 2: [-1, -1, -1]}, 3, 2),
    ],
)
# fmt: on
def test_failure(tmp_path, timing_map, n_tasks, retries):
    def partial_map_function(x):
        return deterministic_failure(tmp_path, timing_map, x)

    with pytest.raises(RuntimeError):
        run_test(
            function=partial_map_function,
            input=range(n_tasks),
            retries=retries,
        )

    check_invocation_counts(tmp_path, timing_map, n_tasks, retries)


def read_int_from_file(path):
    with open(path) as f:
        return int(f.read())


def write_int_to_file(path, i):
    with open(path, "w") as f:
        f.write(str(i))


def deterministic_failure(path, timing_map, i):
    """A function that can either run normally, run slowly, or raise
    an exception, depending on input and invocation count.
    The timing_map is a dictionary whose keys are inputs and values
    are sequences of timing information for each invocation.
    The maginitude of the value is the time to sleep in seconds, and
    the sign indicates the input is returned normally (positive, or 0),
    or an exception is raised (negative).
    If a input is missing then all invocations will run normally.
    If there are subsequent invocations to the ones in the sequence, then
    they will all run normally.
    """
    # increment number of invocations of this function with arg i
    invocation_count_file = path / str(i)
    if invocation_count_file.exists():
        invocation_count = read_int_from_file(invocation_count_file)
    else:
        invocation_count = 0
    write_int_to_file(invocation_count_file, invocation_count + 1)

    timing_code = 0
    if i in timing_map:
        timing_codes = timing_map[i]
        if invocation_count >= len(timing_codes):
            timing_code = 0
        else:
            timing_code = timing_codes[invocation_count]

    if timing_code >= 0:
        time.sleep(timing_code)
        return i
    else:
        time.sleep(-timing_code)
        raise RuntimeError(
            f"Deliberately fail on invocation number {invocation_count + 1} for input {i}"
        )


def check_invocation_counts(
    path, timing_map, n_tasks, retries=None, expected_invocation_counts_overrides=None
):
    expected_invocation_counts = {}
    for i in range(n_tasks):
        if i not in timing_map:
            expected_invocation_counts[i] = 1
        else:
            timing_codes = timing_map[i]
            expected_invocation_count = len(timing_codes) + 1

            if retries is not None:
                # there shouldn't have been more than retries + 1 invocations
                max_invocations = retries + 1
                expected_invocation_count = min(
                    expected_invocation_count, max_invocations
                )

            expected_invocation_counts[i] = expected_invocation_count

    if expected_invocation_counts_overrides is not None:
        expected_invocation_counts.update(expected_invocation_counts_overrides)

    actual_invocation_counts = {i: read_int_from_file(path / str(i)) for i in range(n_tasks)}

    if actual_invocation_counts != expected_invocation_counts:
        for i, expected_count in expected_invocation_counts.items():
            actual_count = actual_invocation_counts[i]
            if actual_count != expected_count:
                print(
                    f"Invocation count for {i}, expected: {expected_count}, actual: {actual_count}"
                )
    assert actual_invocation_counts == expected_invocation_counts


class FakeResponseFuture:
    def __init__(self, error=False, result=None, done=False):
        self.error = error
        self.done = done
        self._result = result
        self._status = 'ok'
        self._exception = (RuntimeError, RuntimeError('failed'), None)
        self.stats = {'worker_exec_time': 1.0}

    def status(self, throw_except=True, internal_storage=None, check_only=False):
        return self._status

    def result(self, throw_except=True, internal_storage=None):
        return self._result


class TestRetryingFutureUnit:

    def test_should_retry_until_budget_exhausted(self):
        future = RetryingFuture(FakeResponseFuture(), map_function=lambda x: x, input=1, retries=1)
        assert future._should_retry() is True
        future._inc_failure_count()
        assert future.failure_count == 1
        assert future._should_retry() is True
        future._inc_failure_count()
        assert future._should_retry() is False

    def test_cancel_prevents_retry(self):
        future = RetryingFuture(FakeResponseFuture(), map_function=lambda x: x, input=1, retries=5)
        future.cancel()
        assert future._should_retry() is False

    def test_retries_default_to_zero(self):
        future = RetryingFuture(FakeResponseFuture(), map_function=lambda x: x, input=1)
        assert future.retries == 0

    def test_status_and_result_reraise_on_error(self):
        wrapped = FakeResponseFuture(error=True, result='nope')
        future = RetryingFuture(wrapped, map_function=lambda x: x, input=1, retries=0)
        with pytest.raises(RuntimeError, match='failed'):
            future.status()
        with pytest.raises(RuntimeError, match='failed'):
            future.result()

    def test_status_and_result_passthrough_on_success(self):
        wrapped = FakeResponseFuture(error=False, result=42)
        future = RetryingFuture(wrapped, map_function=lambda x: x, input=1)
        assert future.status() == 'ok'
        assert future.result() == 42
        assert future.done is False
        assert future.stats == wrapped.stats

    def test_retry_resubmits_original_input_and_kwargs(self):
        replacement = FakeResponseFuture(result=99)
        executor = MagicMock()
        executor.map.return_value = [replacement]
        future = RetryingFuture(
            FakeResponseFuture(error=True),
            map_function=str,
            input=7,
            retries=1,
            timeout=11,
        )
        future._retry(executor)
        executor.map.assert_called_once_with(str, [7], timeout=11)
        assert future.response_future is replacement


class TestRetryingFunctionExecutorUnit:

    def test_map_uses_config_retries_and_forwards_kwargs(self):
        inner = MagicMock()
        inner.config = {'lithops': {'retries': 4}}
        inner.map.return_value = [FakeResponseFuture(), FakeResponseFuture()]
        executor = RetryingFunctionExecutor(inner)

        futures = executor.map(
            lambda x: x,
            [1, 2],
            timeout=9,
            extra_env={'A': '1'},
            chunksize=3,
            obj_chunk_size=10,
            obj_chunk_number=2,
            obj_newline=None,
        )

        assert [f.retries for f in futures] == [4, 4]
        assert [f.input for f in futures] == [1, 2]
        inner.map.assert_called_once()
        kwargs = inner.map.call_args.kwargs
        assert kwargs['timeout'] == 9
        assert kwargs['extra_env'] == {'A': '1'}
        assert kwargs['chunksize'] == 3
        assert kwargs['obj_chunk_size'] == 10
        assert kwargs['obj_chunk_number'] == 2
        assert kwargs['obj_newline'] is None
        assert futures[0].map_kwargs['timeout'] == 9

    def test_explicit_retries_override_config(self):
        inner = MagicMock()
        inner.config = {'lithops': {'retries': 4}}
        inner.map.return_value = [FakeResponseFuture()]
        executor = RetryingFunctionExecutor(inner)

        futures = executor.map(lambda x: x, [1], retries=0)
        assert futures[0].retries == 0

    def test_wait_retries_failed_futures_until_all_complete(self):
        first = FakeResponseFuture(error=True)
        retried = FakeResponseFuture(error=False, result=1)
        inner = MagicMock()
        inner.config = {}
        inner.wait.side_effect = [
            ([first], []),
            ([retried], []),
        ]
        inner.map.return_value = [retried]

        retrying = RetryingFuture(first, map_function=lambda x: x, input=1, retries=1)
        executor = RetryingFunctionExecutor(inner)
        done, pending = executor.wait([retrying], throw_except=False)

        assert pending == []
        assert done == [retrying]
        assert retrying.response_future is retried
        inner.map.assert_called_once()

    def test_wait_always_returns_after_first_poll(self):
        pending_resp = FakeResponseFuture()
        inner = MagicMock()
        inner.config = {}
        inner.wait.return_value = ([], [pending_resp])
        retrying = RetryingFuture(pending_resp, map_function=lambda x: x, input=1, retries=0)
        executor = RetryingFunctionExecutor(inner)

        done, pending = executor.wait([retrying], return_when=ALWAYS)
        assert done == []
        assert pending == [retrying]
        assert inner.wait.call_count == 1

    def test_wait_any_completed_stops_when_one_succeeds(self):
        finished = FakeResponseFuture(error=False, result=1)
        pending = FakeResponseFuture()
        inner = MagicMock()
        inner.config = {}
        inner.wait.return_value = ([finished], [pending])
        done_f = RetryingFuture(finished, map_function=lambda x: x, input=1, retries=0)
        pending_f = RetryingFuture(pending, map_function=lambda x: x, input=2, retries=0)
        executor = RetryingFunctionExecutor(inner)
        done, still_pending = executor.wait(
            [done_f, pending_f], return_when=ANY_COMPLETED
        )
        assert done == [done_f]
        assert still_pending == [pending_f]
        assert inner.wait.call_count == 1

    def test_wait_a_percentage_returns_once_that_share_is_done(self):
        """A percentage return_when used to loop for ever, even with every call done"""
        finished = [FakeResponseFuture(error=False, result=i) for i in range(2)]
        pending = [FakeResponseFuture() for _ in range(2)]
        inner = MagicMock()
        inner.config = {}
        inner.wait.return_value = (finished, pending)
        fs = [RetryingFuture(f, map_function=lambda x: x, input=i, retries=0)
              for i, f in enumerate(finished + pending)]
        executor = RetryingFunctionExecutor(inner)
        done, still_pending = executor.wait(fs, return_when=50)
        assert done == fs[:2]
        assert still_pending == fs[2:]
        assert inner.wait.call_count == 1

    def test_wait_on_no_futures_returns_at_once(self):
        """ANY_COMPLETED used to wait for ever for one of no futures"""
        inner = MagicMock()
        inner.config = {}
        inner.wait.side_effect = [([], [])]
        executor = RetryingFunctionExecutor(inner)
        assert executor.wait([], return_when=ANY_COMPLETED) == ([], [])
        assert executor.wait([]) == ([], [])

    def test_wait_exhausted_retries_are_treated_as_done(self):
        failed = FakeResponseFuture(error=True)
        inner = MagicMock()
        inner.config = {}
        inner.wait.return_value = ([failed], [])
        retrying = RetryingFuture(failed, map_function=lambda x: x, input=1, retries=0)
        executor = RetryingFunctionExecutor(inner)
        done, pending = executor.wait([retrying], throw_except=False)
        assert pending == []
        assert done == [retrying]
        inner.map.assert_not_called()

    def test_context_manager_and_clean_delegate(self):
        inner = MagicMock()
        executor = RetryingFunctionExecutor(inner)
        with executor:
            pass
        inner.__enter__.assert_called_once()
        inner.__exit__.assert_called_once()
        executor.clean('fs', 'cs', False, True, True)
        inner.clean.assert_called_once_with('fs', 'cs', False, True, True)

    def test_retries_to_use_prefers_explicit_then_config(self):
        inner = MagicMock()
        inner.config = {'lithops': {'retries': 9}}
        executor = RetryingFunctionExecutor(inner)
        assert executor._retries_to_use(3) == 3
        assert executor._retries_to_use(None) == 9
        executor.config = {}
        assert executor._retries_to_use(None) == 0


def test_wait_retries_with_the_default_throw_except(tmp_path):
    """The first failure used to end the wait instead of being retried"""
    timing_map = {0: [-1]}

    def partial_map_function(x):
        return deterministic_failure(tmp_path, timing_map, x)

    fexec = FunctionExecutor(config=pytest.lithops_config)
    with RetryingFunctionExecutor(fexec) as executor:
        futures = executor.map(partial_map_function, range(2), retries=1)
        done, pending = executor.wait(futures)
    assert pending == []
    assert sorted(f.result() for f in done) == [0, 1]
    check_invocation_counts(tmp_path, timing_map, 2, retries=1)


def test_wait_raises_by_default_once_retries_are_exhausted(tmp_path):
    timing_map = {0: [-1, -1]}

    def partial_map_function(x):
        return deterministic_failure(tmp_path, timing_map, x)

    fexec = FunctionExecutor(config=pytest.lithops_config)
    with RetryingFunctionExecutor(fexec) as executor:
        futures = executor.map(partial_map_function, range(2), retries=1)
        with pytest.raises(RuntimeError, match='Deliberately fail'):
            executor.wait(futures)
    check_invocation_counts(tmp_path, timing_map, 2, retries=1)


def _count_lines(obj):
    return obj.data_stream.read().count(b'\n')


def _count_lines_from(obj, skip):
    return obj.data_stream.read().count(b'\n') - skip


def test_a_directory_is_retried_one_file_at_a_time(tmp_path):
    """Each file is a call of its own, and a retry runs only the one that failed"""
    data = tmp_path / 'data'
    data.mkdir()
    for name, lines in (('a.txt', 1), ('b.txt', 2), ('c.txt', 3)):
        (data / name).write_text('x\n' * lines)
    calls = tmp_path / 'calls'
    calls.mkdir()

    def count_lines(obj):
        name = os.path.basename(obj.path)
        first = not any(f.startswith(name) for f in os.listdir(calls))
        (calls / f'{name}.{uuid.uuid4().hex}').touch()
        if name == 'b.txt' and first:
            raise RuntimeError('Deliberately fail on the first read of b.txt')
        return obj.data_stream.read().count(b'\n')

    fexec = FunctionExecutor(config=pytest.lithops_config)
    with RetryingFunctionExecutor(fexec) as executor:
        futures = executor.map(count_lines, [str(data)], retries=1)
        done, pending = executor.wait(futures)
    assert pending == []
    assert sorted(f.result() for f in done) == [1, 2, 3]
    assert sorted(f.rsplit('.', 1)[0] for f in os.listdir(calls)) == ['a.txt', 'b.txt', 'b.txt', 'c.txt']


class TestRetryingThrowExcept:

    def test_result_and_status_honour_throw_except_false(self):
        future = RetryingFuture(FakeResponseFuture(error=True, result='partial'), lambda x: x, 1)
        assert future.result(throw_except=False) == 'partial'
        assert future.status(throw_except=False) == 'ok'

    def test_inner_wait_never_raises_and_the_outer_one_reraises_at_the_end(self):
        first = FakeResponseFuture(error=True)
        still_failing = FakeResponseFuture(error=True)
        inner = MagicMock()
        inner.config = {}
        inner.wait.side_effect = [([first], []), ([still_failing], [])]
        inner.map.return_value = [still_failing]
        retrying = RetryingFuture(first, map_function=lambda x: x, input=1, retries=1)

        with pytest.raises(RuntimeError, match='failed'):
            RetryingFunctionExecutor(inner).wait([retrying])

        assert inner.map.call_count == 1
        assert [c.kwargs['throw_except'] for c in inner.wait.call_args_list] == [False, False]


class TestRetryingMapInputs:

    @staticmethod
    def _inner(n_futures, objects=()):
        """An executor whose storage, of the localhost backend, lists ``objects``"""
        inner = MagicMock()
        inner.config = {}
        inner.map.return_value = [FakeResponseFuture() for _ in range(n_futures)]
        inner.internal_storage = SimpleNamespace(backend='localhost', storage=MagicMock())
        inner.internal_storage.storage.list_objects.return_value = list(objects)
        return inner

    @pytest.mark.parametrize('chunks', [{'obj_chunk_number': 2}, {'obj_chunk_size': 64}])
    def test_object_chunks_are_refused_before_invoking(self, chunks):
        inner = self._inner(4)
        with pytest.raises(ValueError, match='obj_chunk'):
            RetryingFunctionExecutor(inner).map(
                _count_lines, ['localhost://bucket/a.txt', 'localhost://bucket/b.txt'], **chunks
            )
        inner.map.assert_not_called()

    def test_a_prefix_is_split_into_one_input_per_object(self):
        """
        It used to raise once its calls were running, since a retry of one
        of them would have resubmitted the whole prefix
        """
        objects = [
            {'Key': 'prefix/a.txt', 'Size': 2},
            {'Key': 'prefix/', 'Size': 0},
            {'Key': 'prefix/b.txt', 'Size': 4},
        ]
        inner = self._inner(2, objects)
        futures = RetryingFunctionExecutor(inner).map(
            _count_lines_from, ['localhost://bucket/prefix/'], extra_args={'skip': 1}
        )
        expected = [
            {'obj': 'localhost://bucket/prefix/a.txt', 'skip': 1},
            {'obj': 'localhost://bucket/prefix/b.txt', 'skip': 1},
        ]
        assert [f.input for f in futures] == expected
        assert inner.map.call_args.args[1] == expected
        inner.internal_storage.storage.list_objects.assert_called_once_with('bucket', 'prefix/', None)
        # Merged into every input already, so neither the map nor a retry adds them again
        assert inner.map.call_args.kwargs['extra_args'] is None
        assert all(f.map_kwargs['extra_args'] is None for f in futures)

    def test_a_directory_is_split_into_one_input_per_file(self, tmp_path):
        for name in ('a.txt', 'b.txt'):
            (tmp_path / name).write_text('x\n')
        futures = RetryingFunctionExecutor(self._inner(2)).map(_count_lines, [str(tmp_path)])
        assert sorted(f.input['obj'] for f in futures) == [
            str(tmp_path / 'a.txt'), str(tmp_path / 'b.txt')
        ]

    def test_single_objects_are_not_listed(self, tmp_path):
        local_file = tmp_path / 'a.txt'
        local_file.write_text('x\n')
        inner = self._inner(1)
        futures = RetryingFunctionExecutor(inner).map(_count_lines, ['localhost://bucket/a.txt'])
        assert [f.input for f in futures] == [{'obj': 'localhost://bucket/a.txt'}]
        inner.internal_storage.storage.list_objects.assert_not_called()
        inner.internal_storage.storage.head_object.assert_not_called()
        futures = RetryingFunctionExecutor(self._inner(1)).map(_count_lines, [str(local_file)])
        assert [f.input for f in futures] == [{'obj': str(local_file)}]

    def test_a_glob_is_listed_only_where_the_backend_globs(self):
        inner = self._inner(1, [{'Key': 'data/a.csv', 'Size': 1}])
        inner.internal_storage.backend = 'aws_s3'
        futures = RetryingFunctionExecutor(inner).map(_count_lines, ['aws_s3://bucket/data/*.csv'])
        assert [f.input for f in futures] == [{'obj': 'aws_s3://bucket/data/a.csv'}]

        inner = self._inner(1)
        futures = RetryingFunctionExecutor(inner).map(_count_lines, ['localhost://bucket/a*.txt'])
        assert [f.input for f in futures] == [{'obj': 'localhost://bucket/a*.txt'}]
        inner.internal_storage.storage.list_objects.assert_not_called()

    def test_a_prefix_with_no_objects_is_refused_before_invoking(self):
        inner = self._inner(0)
        with pytest.raises(Exception, match='No objects found'):
            RetryingFunctionExecutor(inner).map(_count_lines, ['localhost://bucket/empty/'])
        inner.map.assert_not_called()

    def test_more_calls_than_inputs_is_an_error(self):
        inner = self._inner(3)
        with pytest.raises(ValueError, match='cannot be retried'):
            RetryingFunctionExecutor(inner).map(lambda x: x, [1, 2])

    def test_a_generator_is_paired_with_its_futures(self):
        inner = self._inner(3)
        futures = RetryingFunctionExecutor(inner).map(lambda x: x, (i for i in range(3)))
        assert [f.input for f in futures] == [0, 1, 2]
        assert inner.map.call_args.args[1] == [0, 1, 2]

    def test_a_chain_after_map_reduce_pairs_the_reduce_future_only(self):
        map_stage = [SimpleNamespace(_mapreduce_map=True) for _ in range(3)]
        reducer = SimpleNamespace(_mapreduce_map=False)
        inner = self._inner(1)
        futures = RetryingFunctionExecutor(inner).map(lambda x: x, FuturesList(map_stage + [reducer]))
        assert [f.input for f in futures] == [reducer]
