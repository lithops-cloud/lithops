"""
Simple Lithops example where a single function, invoked with
call_async(), runs a map() of its own from inside the cloud.
"""
import lithops


def my_map_function(id, x):
    print(f"I'm activation number {id}")
    return x + 7


def scheduler(total):
    iterdata = range(total)
    fexec = lithops.FunctionExecutor()
    return fexec.map(my_map_function, iterdata)


if __name__ == "__main__":
    fexec = lithops.FunctionExecutor()
    fexec.call_async(scheduler, 5)
    print(fexec.get_result())
    fexec.clean()
