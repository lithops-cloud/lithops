from dso.client import Client
from jpype import *
from jpype import java
import lithops

def my_function(x):
    client = Client("35.188.231.186:11222")
    d = client.getAtomicCounter("cnt")
    return d.increment()+7

if __name__ == '__main__':
    fexec = lithops.FunctionExecutor(runtime='0track/lithops-dso:1.1')
    fexec.call_async(my_function, 3)
    client = Client("35.188.231.186:11222")
    c = client.getAtomicCounter("cnt")
    print("counter: "+str(c.increment()))
    print(fexec.get_result())
