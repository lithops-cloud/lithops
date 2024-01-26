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
   $ flake8 lithops --count --max-line-length=180 --statistics --ignore W605
   ``` 
6. Add new unit tests for your code.


Functional testing
------------------

To test that all is working as expected, run either:

```bash
$ lithops test
```

or 

```bash
$ python3 -m lithops.tests.tests_main
```

If you made changes to a specific backend, please run tests on that backend. For example, if you made changes to the AWS Lambda backend, run the tests with:

```bash
$ lithops test -b aws_lambda -s aws_s3
```

Please follow the guidelines in [docs/testing.md](docs/source/testing.rst) for more details.
