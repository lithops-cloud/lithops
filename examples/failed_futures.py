"""
Simple Lithops example showing what happens when a function fails.

Some of the functions below raise an exception. Passing
throw_except=False to get_result() makes Lithops hand back what it has
instead of re-raising, so the successful calls can be told apart from
the failed ones.
"""
import lithops
import time


def my_map_function(id, x):
    print(f"I'm activation number {id}")
    time.sleep(2)
    if id in [2, 4]:
        raise MemoryError()
    return x


if __name__ == "__main__":
    iterdata = ["a", "b", "c", "d", "e"]

    fexec = lithops.FunctionExecutor(log_level='DEBUG')
    futures = fexec.map(my_map_function, iterdata)
    return_vals = fexec.get_result(fs=futures, throw_except=False)

    failed_callids = [int(f.call_id) for f in futures if f.error]

    if failed_callids:
        new_iterdata = [iterdata[i] for i in failed_callids]
        futures = fexec.map(my_map_function, new_iterdata)
        new_return_vals = fexec.get_result(fs=futures, throw_except=False)

        for i, failed_callid in enumerate(failed_callids):
            return_vals[failed_callid] = new_return_vals[i]

    print(return_vals)
