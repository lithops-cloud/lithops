"""
Simple Lithops example using one single function invocation
with a class as a function and a function as a parameter
"""
import lithops

def mult(x, y):
    return x + y


class MyClass:
    def __init__(self, base) -> None:
        self.base = base

    def __call__(self, x, fn) -> int:
        return fn(self.base, x)


if __name__ == '__main__':
    fexec = lithops.FunctionExecutor()
    inst = MyClass(7)
    fexec.map(inst, [(8, mult), (6, mult)])
    print(fexec.get_result())
