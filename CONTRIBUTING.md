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
3. Make sure that your code passes the unit tests.
4. Make sure that your code passes the linter. 
5. Add new unit tests for your code.


Unit testing
------------

To test that all is working as expected, use the command:

```bash
$ lithops test
```

Before adding new tests for existing / new features, please follow the guidelines in docs/testing.


[comment]: <> (or)

[comment]: <> (```bash)

[comment]: <> ($ python3 -m lithops.scripts.tests)

[comment]: <> (```)

[comment]: <> (Notice that if you didn't set a local Lithops's config file, you need to provide it as a json file path by `-c <CONFIG>` flag.)

[comment]: <> (For more information please refer to testing.md)

[comment]: <> (Alternatively, for debugging purposes, you can run specific tests by `-t <TESTNAME>`. use `--help` flag to get more information about the test script.)
