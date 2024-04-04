import logging
from pathlib import Path
import tempfile
import time
import unittest

from lithops.executors import LocalhostExecutor
from lithops.retries import RetryingFunctionExecutor

logger = logging.getLogger(__name__)


class TestRetries(unittest.TestCase):

    def test_retries_success_no_failures(self):
        self.run_map({}, 3, 2)

    def test_retries_success_first_invocation_fails(self):
        self.run_map({0: [-1], 1: [-1], 2: [-1]}, 3, 2)

    def test_retries_success_first_two_invocations_fail(self):
        self.run_map({0: [-1, -1], 1: [-1, -1], 2: [-1, -1]}, 3, 2)

    def test_retries_success_first_input_sleeps_once(self):
        self.run_map({0: [20]}, 3, 2)

    def test_retries_failure(self):
        with self.assertRaises(RuntimeError):
            self.run_map({0: [-1], 1: [-1], 2: [-1, -1, -1]}, 3, 2)

    def run_map(self, timing_map, n_tasks, retries, timeout=10):
        fexec = LocalhostExecutor()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            def map_function(x):
                return deterministic_failure(tmp_path, timing_map, x)
            input = range(n_tasks)
            with RetryingFunctionExecutor(fexec) as executor:
                futures = executor.map(
                    map_function,
                    input,
                    timeout=timeout,
                    retries=retries,
                )
                done, pending = executor.wait(futures, throw_except=False)
                assert len(pending) == 0
            outputs = set(f.result() for f in done)

            assert outputs == set(range(n_tasks))

            self.check_invocation_counts(tmp_path, timing_map, n_tasks, retries)

    def check_invocation_counts(
        self, path, timing_map, n_tasks, retries=None, expected_invocation_counts_overrides=None
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
        self.assertEqual(actual_invocation_counts, expected_invocation_counts)


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
            f"Deliberately fail on invocation number {invocation_count+1} for input {i}"
        )
