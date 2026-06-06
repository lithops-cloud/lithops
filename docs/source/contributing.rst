.. _contributing:

Contributing to Lithops
=======================

Reporting bugs and asking questions
-----------------------------------

You can post questions or issues or feedback through the following channels:

1. `GitHub Discussions <https://github.com/lithops-cloud/lithops/discussions>`_: For discussions about development, questions about usage, and feature requests.
2. `GitHub Issues <https://github.com/lithops-cloud/lithops/issues>`_: For bug reports and feature requests.


To contribute a patch
---------------------

1. Break your work into small, single-purpose patches if possible. It's much
   harder to merge in a large change with a lot of disjoint features.
2. Submit the patch as a GitHub pull request against the master branch.
3. Make sure that your code passes the tests.
4. Make sure that your code passes the linter. Install ``flake8`` with ``pip3 install flake8`` and run the following command until you don't see any linting errors:

   .. code:: bash

      flake8 lithops --count --max-line-length=180 --statistics --ignore W605,W503

5. Add new tests for your code.


Testing
-------

To test that all is working as expected, install ``pytest``, navigate to the tests folder ``lithops/tests/``, and execute:

.. code:: bash

   pytest -v

If you made changes to a specific backend, please run tests on that backend.
For example, if you made changes to the AWS Lambda backend, execute the tests with:

.. code:: bash

   pytest -v --backend aws_lambda --storage aws_s3

You can list all the available tests using:

.. code:: bash

   pytest --collect-only

To run a specific test or group of tests, use the ``-k`` parameter, for example:

.. code:: bash

   pytest -v --backend localhost --storage localhost -k test_map

To view all the Lithops logs during the tests in DEBUG mode, execute:

.. code:: bash

   pytest -o log_cli=true --log-cli-level=DEBUG --backend localhost --storage localhost
