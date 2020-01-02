# PyWren on vanilla OpenWhisk

PyWren can also run on vanilla OpenWhisk installations, for example by deploying OpenWhisk with [openwhisk-devtools](https://github.com/apache/openwhisk-devtools).

Once you have your deployment ready, you need to install the [openwhisk-cli](https://github.com/apache/openwhisk-cli) and then ensure you can run end-to-end [python example](https://github.com/apache/openwhisk/blob/master/docs/actions-python.md). 

For example, create a file named `hello.py` with the next content:

```python
def main(args):
    name = args.get("name", "stranger")
    greeting = "Hello " + name + "!"
    print(greeting)
    return {"greeting": greeting}
```

Now issue the `wsk` command to deploy the python action:

```
$ wsk action create helloPython hello.py
```

Finally, test the helloPython action:

```
$ wsk action invoke --result helloPython --param name World
```

If everything is working fine, you can proceed to configure PyWren. To do so, edit *~/.pywren_config* and add the next section::

```yaml
openwhisk:
    endpoint    : <OW_ENDPOINT>
    namespace   : <NAMESPACE>
    api_key     : <AUTH_KEY>
    insecure    : <True/False>
```

You can find all the values in `~/.wskprops` file. For example, the content of the file should looks like:

```
APIHOST=192.168.1.30
AUTH=23bc46b1-71f6-4ed5-8c54-816aa4f8c50:123zO3xZCLrMN6v2BKK1dXYFpXlPkccOFqm12CdAsMgRU4VrNZ9lyGVCG
INSECURE_SSL=true
NAMESPACE=guest
```

Copy all the values into the pywren config file as:

```yaml
openwhisk:
    endpoint    : https://192.168.1.30
    namespace   : guest
    api_key     : 23bc46b1-71f6-4ed5-8c54-816aa4f8c50:123zO3xZCLrMN6v2BKK1dXYFpXlPkccOFqm12CdAsMgRU4VrNZ9lyGVCG
    insecure    : True
```

Once configured, you can start running functions:

```python
import pywren_ibm_cloud as pywren

def add_seven(x):
    return x + 7

if __name__ == '__main__':
    wsk = pywren.openwhisk_executor()
    wsk.call_async(add_seven, 3)
    print(wsk.get_result())
```
