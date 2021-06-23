Lithops Function chaining (beta)
===================

- Note: This API is beta and may be revised in future releases. If you encounter any bugs, please open an issue on GitHub.

Function chaining is a pattern where multiple functions are called on the same executor consecutively. Using the same `lithops.FunctionExecutor` object reference, multiple functions can be invoked. It increases the readability of the code and means less redundancy. This means we chain multiple functions together with the same element reference. It’s not necessary to attach the `lithops.FunctionExecutor` reference multiple times for each function call.

This patter is specially useful when the output of one invocation is the input of another invocation. In this case, Lithops does not download the intermediate results to the local client, instead, the intermediate results are directly read from the next function.

It currently works with the [Futures API](api_futures.md), and you can chain the `map()`, `map_reuce()`, `wait()` and `get_result()` methods. View the next examples:


Getting the result from a single `map()` call:

```python
import lithops

def my_func1(x):
    return x*2

iterdata = [1, 2, 3]

fexec = lithops.FunctionExecutor()
res = fexec.map(my_func1, iterdata).get_result()
print(res)
```


Chain multiple map() calls and get the final result:

```python
import lithops


def my_func1(x):
    return x*2, 5
    
def my_func2(x, y):
    return x+y

iterdata = [1, 2, 3]

fexec = lithops.FunctionExecutor()
res = fexec.map(my_func1, iterdata).map(my_func2).get_result()
print(res)
```

There is no limit in the number of map() calls than can be chained:

```python
def my_func1(x):
    return x+2, 5


def my_func2(x, y):
    return x+y, 5, 2


def my_func3(x, y, z):
    return x+y+z


iterdata = [1, 2, 3]

fexec = lithops.FunctionExecutor()
res = fexec.map(my_func1, data).map(my_func2).map(my_func3).get_result()
print(res)
```

Alternatively, you can pass the `futures` generated in a `map()` or `map_reduce()` call to the `iterdata` parameter with the same effect:

```python
def my_func1(x):
    return x+2, 5


def my_func2(x, y):
    return x+y, 5, 2


def my_func3(x, y, z):
    return x+y+z


iterdata = [1, 2, 3]

fexec = lithops.FunctionExecutor()
futures1 = fexec.map(my_func1, iterdata)
futures2 = fexec.map(my_func2, futures1)
futures3 = fexec.map(my_func3, futures2)
final_result = fexec.get_result(futures3)

print(final_result)
```