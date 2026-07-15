Installing Lithops
==================

You can install Lithops using ``pip``:

.. code-block::

   $ pip3 install lithops

This will install the latest version.

If you already have Lithops installed, you can upgrade to the latest version using ``pip``:

.. code-block::

   $ pip3 install --upgrade lithops

You can also install Lithops from GitHub and use the master branch. Using the master branch allows you to use the latest features and bug fixes, but keep in mind that the master branch is considered unstable, and you may encounter problems caused by features that are still under development.

.. code::

   $ git clone https://github.com/lithops-cloud/lithops
   $ cd lithops
   $ pip3 install .

It is recommended to use a Virtual Environment for your Python project that uses Lithops. Without a Virtual Environment, ``pip`` will install Lithops globally, while with a Virtual Environment, Lithops is installed locally and is only available when the Virtual Environment is activated.

.. code::

   $ python3 -m venv lithops-venv
   $ source lithops-venv/bin/activate
   (lithops-venv) $ pip install lithops

