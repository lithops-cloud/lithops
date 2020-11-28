from dso.client import Client
from jpype import *
from jpype import java
import lithops

def my_map_function(id, x):
    client = Client("35.188.231.186:11222")
    c = client.getAtomicCounter("cnt")
    c.increment(x)
    b = client.getCyclicBarrier("b", len(iterdata))
    b.waiting()
    return c.tally()

if __name__ == "__main__":
    f = Client("35.188.231.186:11222")
    c = f.getAtomicCounter("cnt")
    c.reset()
    iterdata = [1, 2, 3, 4]
    fexec = lithops.FunctionExecutor(runtime='0track/lithops-dso:1.1')
    fexec.map(my_map_function, iterdata)
    print(fexec.get_result())
    print(c.tally())
    fexec.clean()
