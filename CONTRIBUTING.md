Contributing to Lithops
===================

Reporting bugs and asking questions
-----------------------------------

You can post questions or issues or feedback through the following channels:

1. `Github Discussions`_: For discussions about development, questions about usage, and feature requests.
2. `GitHub Issues`_: For bug reports and feature requests.


To contribute a patch:
----------------------

1. Break your work into small, single-purpose patches if possible. It's much
   harder to merge in a large change with a lot of disjoint features.
2. Submit the patch as a GitHub pull request against the master branch.
3. Make sure that your code passes the unit tests.
4. Make sure that your code passes the linter. 
5. Add new unit tests for your code.

.. _`Github Discussions`: https://github.com/lithops-cloud/lithops/discussions
.. _`GitHub Issues`: https://github.com/lithops-cloud/lithops/issues

PR Review Process
-----------------

For contributors who are in the lithops-cloud organization:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- When you first create a PR, add an reviewer to the `assignee` section.
- Assignees will review your PR and add `@author-action-required` label if further actions are required.
- Address their comments and remove `@author-action-required` label from the PR.
- Repeat this process until assignees approve your PR.
- Once the PR is approved, the author is in charge of ensuring the PR passes the build. Add `test-ok` label if the build succeeds.
- Committers will merge the PR once the build is passing.


Unit testing
------------

To test that all is working, use the command:

```bash
$ lithops verify
```

or

```bash
$ python3 -m lithops.tests
```

Notice that if you didn't set a local Lithops's config file, you need to provide it as a json file path by `-c <CONFIG>` flag.

Alternatively, for debugging purposes, you can run specific tests by `-t <TESTNAME>`. use `--help` flag to get more information about the test script.
