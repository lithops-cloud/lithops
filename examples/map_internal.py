"""
Simple Lithops example using the call_async method.
to spawn an internal map execution.
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
