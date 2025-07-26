import lithops
from lithops.storage import Storage
from lithops import RetryingFunctionExecutor

# Dictionary of known failures: how many times each input should fail before succeeding
# This must be available to each function at runtime, so hardcoded or passed in as data
FAILURE_MAP = {
    0: 1,  # fail once
    1: 2,  # fail twice
    2: 0,  # succeed immediately
    3: 3,  # fail three times (requires at least retries=3)
}

bucket = 'storage'


def my_retry_function(x):
    storage = Storage()

    key = f"retries-demo/input-{x}"
    try:
        count = int(storage.get_object(bucket, key))
    except Exception:
        count = 0

    print(f"[Input {x}] Attempt #{count + 1}")

    if count < FAILURE_MAP.get(x, 0):
        # Store updated count before failing
        storage.put_object(bucket, key, str(count + 1))
        raise RuntimeError(f"Deliberate failure for input {x}, attempt {count + 1}")

    return x + 100


if __name__ == "__main__":
    iterdata = [0, 1, 2, 3]

    with lithops.FunctionExecutor() as fexec:
        with RetryingFunctionExecutor(fexec) as retry_exec:
            futures = retry_exec.map(my_retry_function, iterdata)
            done, not_done = retry_exec.wait(futures, throw_except=False)
            outputs = set(f.result() for f in done)

    Storage().delete_objects(bucket, [f"retries-demo/input-{x}" for x in iterdata])
    print("Final results:", outputs)
