# How to contribute

## Contribute code

Please contribute using [Github Flow](https://guides.github.com/introduction/flow/). Create a branch, add commits, and [open a pull request](https://github.com/lithops-cloud/lithops/compare/).

## Verify - Unit Testing

To test that all is working, use the command:

```bash
$ lithops verify
```

or

```bash
$ python -m lithops.tests
```

Notice that if you didn't set a local Lithops's config file, you need to provide it as a json file path by `-c <CONFIG>` flag.

Alternatively, for debugging purposes, you can run specific tests by `-t <TESTNAME>`. use `--help` flag to get more information about the test script.
