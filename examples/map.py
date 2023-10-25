"""
Simple Lithops example using the map method.
In this example the map() method will launch one
map function for each entry in 'iterdata'. Finally
it will print the results for each invocation with
fexec.get_result()
"""
import lithops
import time


def my_map_function(id, x):
    print(f"I'm activation number {id}")
    time.sleep(5)
    return x + 7


if __name__ == "__main__":
    iterdata = [1, 2, 3, 4]
    fexec = lithops.FunctionExecutor()
    fexec.map(my_map_function, range(2))
    fexec.map(my_map_function, range(6))
    print(fexec.get_result())
