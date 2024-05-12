Contributing to Lithops
===================

Reporting bugs and asking questions
-----------------------------------

You can post questions or issues or feedback through the following channels:

1. [Github Discussions](https://github.com/lithops-cloud/lithops/discussions): For discussions about development, questions about usage, and feature requests.
2. [GitHub Issues](https://github.com/lithops-cloud/lithops/issues): For bug reports and feature requests.


To contribute a patch:
----------------------

1. Break your work into small, single-purpose patches if possible. It's much
   harder to merge in a large change with a lot of disjoint features.
2. Submit the patch as a GitHub pull request against the master branch.
3. Make sure that your code passes the functional tests. See the [Functional testing](#functional-testing) section below.
4. Make sure that your code passes the linter. Install `flake8` with `pip3 install flake8` and run the next command until you don't see any linitng error:
   ```bash
   flake8 lithops --count --max-line-length=180 --statistics --ignore W605,W503
   ``` 
6. Add new unit tests for your code.


Testing
-------

To test that all is working as expected, you must install `pytest`, navigate to the tests folder `lithops/tests/`, and execute:
```bash
pytest -v
```

If you made changes to a specific backend, please run tests on that backend.
For example, if you made changes to the AWS Lambda backend, execute the tests with:
```bash
pytest -v --backend aws_lambda --storage aws_s3
```

You can list all the available tests using:
```bash
pytest --collect-only
```

To run a specific test or group of tests, use the `-k` parameter, for example:
```bash
pytest -v --backend localhost --storage localhost -k test_map
```

To view all the Lithops logs during the tests, and in DEBUG mode, execute:
```bash
pytest -o log_cli=true --log-cli-level=DEBUG --backend localhost --storage localhost
```
