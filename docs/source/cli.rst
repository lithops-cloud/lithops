Lithops Command Line Tool
=========================

Lithops is shipped with a *command line tool* (or cli) called
``lithops``. It brings **runtime**, **logs**, and **storage** management
to the terminal of your computer. Lithops CLI is automatically installed
when you install Lithops through ``pip3 install lithops``.

Lithops management
------------------

``lithops hello``
~~~~~~~~~~~~~~~~~

Runs a *hello-world* function.

+-----------------+------------------------------+
| Parameter       | Description                  |
+=================+==============================+
| --config, -c    | Path to your config file     |
+-----------------+------------------------------+
| --backend, -b   | Compute backend name         |
+-----------------+------------------------------+
| --region, -r    | Compute backend region       |
+-----------------+------------------------------+
| --storage, -s   | Storage backend name         |
+-----------------+------------------------------+
| --debug, -d     | Activate debug logs (Flag)   |
+-----------------+------------------------------+

-  **Usage example**: ``lithops hello -b ibm_cf -s ibm_cos``

``lithops test``
~~~~~~~~~~~~~~~~

Runs the unit testing suite. For more instructions about testing `view
this page <testing.md>`__.

+------------------------+----------------------------------------------------------------+
| Parameter              | Description                                                    |
+========================+================================================================+
| --config, -c           | Path to your config file                                       |
+------------------------+----------------------------------------------------------------+
| --backend, -b          | Compute backend name                                           |
+------------------------+----------------------------------------------------------------+
| --region, -r           | Compute backend region                                         |
+------------------------+----------------------------------------------------------------+
| --storage, -s          | Storage backend name                                           |
+------------------------+----------------------------------------------------------------+
| --debug, -d            | Activate debug logs (Flag)                                     |
+------------------------+----------------------------------------------------------------+
| --test, -t             | Run a specific tester                                          |
+------------------------+----------------------------------------------------------------+
| --groups, -g           | Run all testers belonging to a specific group                  |
+------------------------+----------------------------------------------------------------+
| --fail\_fast, -f       | Stops test run upon first occurrence of a failed test (Flag)   |
+------------------------+----------------------------------------------------------------+
| --keep\_datasets, -k   | Keeps datasets in storage after the test run (Flag)            |
+------------------------+----------------------------------------------------------------+

-  **Usage example**: ``lithops test -b ibm_cf -s ibm_cos``

``lithops clean``
~~~~~~~~~~~~~~~~~

Deletes all the information related to Lithops except the config file.
It includes deployed runtimes and temporary data stored in the storage
backend. Run this command is like *start from scratch* with Lithops. In
some circumstances, when there is some inconsistency between the local
machine and the cloud, it is convenient to run this command.

+-----------------+------------------------------+
| Parameter       | Description                  |
+=================+==============================+
| --config, -c    | Path to your config file     |
+-----------------+------------------------------+
| --backend, -b   | Compute backend name         |
+-----------------+------------------------------+
| --region, -r    | Compute backend region       |
+-----------------+------------------------------+
| --storage, -s   | Storage backend name         |
+-----------------+------------------------------+
| --debug, -d     | Activate debug logs (Flag)   |
+-----------------+------------------------------+
| --all, -a       | Delete all (Flag)            |
+-----------------+------------------------------+

-  **Usage example**: ``lithops clean -b ibm_cf -s ibm_cos``

``lithops attach``
~~~~~~~~~~~~~~~~~~

Open an ssh connection to the master VM (Only available for standalone backends)

+------------------------+----------------------------------------------------------------+
| Parameter              | Description                                                    |
+========================+================================================================+
| --config, -c           | Path to your config file                                       |
+------------------------+----------------------------------------------------------------+
| --backend, -b          | Compute backend name                                           |
+------------------------+----------------------------------------------------------------+
| --region, -r           | Compute backend region                                         |
+------------------------+----------------------------------------------------------------+
| --start                | Start the master VM if needed                                  |
+------------------------+----------------------------------------------------------------+
| --debug, -d            | Activate debug logs (Flag)                                     |
+------------------------+----------------------------------------------------------------+

-  **Usage example**: ``lithops attach -b ibm_vpc``

``lithops worker list``
~~~~~~~~~~~~~~~~~~~~~~~

Lists the available workers in the master VM (Only available for standalone backends)

+------------------------+----------------------------------------------------------------+
| Parameter              | Description                                                    |
+========================+================================================================+
| --config, -c           | Path to your config file                                       |
+------------------------+----------------------------------------------------------------+
| --backend, -b          | Compute backend name                                           |
+------------------------+----------------------------------------------------------------+
| --region, -r           | Compute backend region                                         |
+------------------------+----------------------------------------------------------------+
| --debug, -d            | Activate debug logs (Flag)                                     |
+------------------------+----------------------------------------------------------------+

-  **Usage example**: ``lithops worker list -b ibm_vpc``

``lithops job list``
~~~~~~~~~~~~~~~~~~~~

Lists the jobs submitted to the master VM (Only available for standalone backends)

+------------------------+----------------------------------------------------------------+
| Parameter              | Description                                                    |
+========================+================================================================+
| --config, -c           | Path to your config file                                       |
+------------------------+----------------------------------------------------------------+
| --backend, -b          | Compute backend name                                           |
+------------------------+----------------------------------------------------------------+
| --region, -r           | Compute backend region                                         |
+------------------------+----------------------------------------------------------------+
| --debug, -d            | Activate debug logs (Flag)                                     |
+------------------------+----------------------------------------------------------------+

-  **Usage example**: ``lithops job list -b ibm_vpc``


Runtime management
------------------

For complete instructions on how to build runtimes for Lithops, please
refer to the ``runtime/`` folder and choose your compute backend.

``lithops runtime build <runtime-name>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Build a new runtime image. Depending of the compute backend, there must
be a Dockerfile located in the same folder you run the command,
otherwise use ``-f`` parameter. Note that this command only builds the
image and puts it into a container registry. This command do not deploy
the runtime to the compute backend.

+-----------------+-----------------------------------+
| Parameter       | Description                       |
+=================+===================================+
| runtime-name    | Name of your runtime              |
+-----------------+-----------------------------------+
| --file, -f      | Path to Dockerfile/requirements   |
+-----------------+-----------------------------------+
| --config, -c    | Path to your config file          |
+-----------------+-----------------------------------+
| --backend, -b   | Compute backend name              |
+-----------------+-----------------------------------+
| --debug, -d     | Activate debug logs (Flag)        |
+-----------------+-----------------------------------+

-  **Usage example**:
   ``lithops runtime build -f Dockefile.pythonv39 -b ibm_cf lithopscloud/my-runtime-name-v39:01``

``lithops runtime deploy <runtime-name>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deploys a new Lithops runtime to the compute backend 
based on an image built with the previous command.
When you build a runtime, for example from a Dockerfile,
the runtime is uploaded to a docker registry, however it is
not deployed to the compute backend. To do so run this command. Note
that the runtime is automatically created/deployed in the compute
backend the first time you run a function with it, so in most of the
cases you can avoid using this command.

+-----------------+------------------------------------------------+
| Parameter       | Description                                    |
+=================+================================================+
| runtime-name    | Name of your runtime                           |
+-----------------+------------------------------------------------+
| --config, -c    | Path to your config file                       |
+-----------------+------------------------------------------------+
| --backend, -b   | Compute backend name                           |
+-----------------+------------------------------------------------+
| --storage, -s   | Storage backend name                           |
+-----------------+------------------------------------------------+
| --debug, -d     | Activate debug logs (Flag)                     |
+-----------------+------------------------------------------------+
| --memory, -m    | Memory size in MBs to assign to the runtime.   |
+-----------------+------------------------------------------------+
| --timeout, -t   | Timeout is seconds to assign to the runtime    |
+-----------------+------------------------------------------------+

-  **Usage example**:
   ``lithops runtime deploy -b ibm_cf lithopscloud/my-runtime-name-v39:01 -m 1024 -t 300``

``lithops runtime update <runtime-name>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Updates an already deployed runtime with the local lithops code.
This command is useful when developers change the local python Lithops
code and want to update the deployed runtimes with it. As an
alternative, you can run ``lithops clean -b <backend-name>`` and then
let Lithops create the runtime automatically with the new Lithops code.

+-----------------+------------------------------+
| Parameter       | Description                  |
+=================+==============================+
| runtime-name    | Name of your runtime         |
+-----------------+------------------------------+
| --config, -c    | Path to your config file     |
+-----------------+------------------------------+
| --backend, -b   | Compute backend name         |
+-----------------+------------------------------+
| --storage, -s   | Storage backend name         |
+-----------------+------------------------------+
| --debug, -d     | Activate debug logs (Flag)   |
+-----------------+------------------------------+

-  **Usage example**:
   ``lithops runtime update -b ibm_cf lithopscloud/my-runtime-name-v39:01``

``lithops runtime list``
~~~~~~~~~~~~~~~~~~~~~~~~

Lists all created/deployed runtimes of an specific compute backend.

+-----------------+------------------------------+
| Parameter       | Description                  |
+=================+==============================+
| --config, -c    | Path to your config file     |
+-----------------+------------------------------+
| --backend, -b   | Compute backend name         |
+-----------------+------------------------------+
| --debug, -d     | Activate debug logs (Flag)   |
+-----------------+------------------------------+

-  **Usage example**: ``lithops runtime list -b ibm_cf``

``lithops runtime delete <runtime-name>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deletes all runtimes created/deployed in the compute backend that
matches the provided runtime-name. As an alternative, you can run
``lithops clean -b <backend-name>`` to delete not only the runtimes that
match the provided runtime-name, but all them.

+-----------------+----------------------------------------------+
| Parameter       | Description                                  |
+=================+==============================================+
| runtime-name    | Name of your runtime                         |
+-----------------+----------------------------------------------+
| --config, -c    | Path to your config file                     |
+-----------------+----------------------------------------------+
| --memory, -m    | Memory size in MBs of the runtime to delete. |
+-----------------+----------------------------------------------+
| --version, -v   | Lithops version of the runtime to delete.    |
+-----------------+----------------------------------------------+
| --backend, -b   | Compute backend name                         |
+-----------------+----------------------------------------------+
| --storage, -s   | Storage backend name                         |
+-----------------+----------------------------------------------+
| --debug, -d     | Activate debug logs (Flag)                   |
+-----------------+----------------------------------------------+

-  **Usage example**:
   ``lithops runtime delete -b ibm_cf -s ibm_cos lithopscloud/my-runtime-name-v39:01``


VM Images management
--------------------

``lithops image build <image-name>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Build a new VM image.

+-----------------+-----------------------------------+
| Parameter       | Description                       |
+=================+===================================+
| image-name      | Name of the VM image              |
+-----------------+-----------------------------------+
| --file, -f      | Path to custom requirements.sh    |
+-----------------+-----------------------------------+
| --config, -c    | Path to your config file          |
+-----------------+-----------------------------------+
| --backend, -b   | Compute backend name              |
+-----------------+-----------------------------------+
| --region, -r    | Compute backend region            |
+-----------------+-----------------------------------+
| --overwrite, -o | Overwrite the VM image if exists  |
+-----------------+-----------------------------------+
| --debug, -d     | Activate debug logs (Flag)        |
+-----------------+-----------------------------------+

-  **Usage example**:
   ``lithops image build -b ibm_vpc``


``lithops image list``
~~~~~~~~~~~~~~~~~~~~~~

Lists all Ubuntu 22 VM images.

+-----------------+-----------------------------------+
| Parameter       | Description                       |
+=================+===================================+
| --config, -c    | Path to your config file          |
+-----------------+-----------------------------------+
| --backend, -b   | Compute backend name              |
+-----------------+-----------------------------------+
| --region, -r    | Compute backend region            |
+-----------------+-----------------------------------+
| --debug, -d     | Activate debug logs (Flag)        |
+-----------------+-----------------------------------+

-  **Usage example**:
   ``lithops image list -b ibm_vpc``


Logs management
---------------

``lithops logs poll``
~~~~~~~~~~~~~~~~~~~~~

Prints to the screen the Lithops function logs as they are produced.

-  **Usage example**: ``lithops logs poll``

``lithops logs get <job-key>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prints to the screen the Lithops function of a specific job.

+-------------+---------------+
| Parameter   | Description   |
+=============+===============+
| job-key     | Job key       |
+-------------+---------------+

-  **Usage example**: ``lithops logs get fa6071-26-M000``

Storage management
------------------

Lithops storage tool can manage all your configured storage backends
with the same set of commands.

``lithops storage put <filename> <bucket>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Uploads a local file to a bucket.

+-----------------+--------------------------------------+
| Parameter       | Description                          |
+=================+======================================+
| filename        | Path of your local file              |
+-----------------+--------------------------------------+
| bucket          | Name of the destination bucket       |
+-----------------+--------------------------------------+
| --key, -k       | Object name. filename if not present |
+-----------------+--------------------------------------+
| --backend, -b   | Storage backend name                 |
+-----------------+--------------------------------------+
| --debug, -d     | Activate debug logs (Flag)           |
+-----------------+--------------------------------------+
| --config, -c    | Path to your config file             |
+-----------------+--------------------------------------+

-  **Usage example**:
   ``lithops storage put -b ibm_cos test.txt cloudbucket``

``lithops storage get <bucket> <key>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Downloads a remote object stored in a bucket to a local file.

+-----------------+------------------------------------+
| Parameter       | Description                        |
+=================+====================================+
| bucket          | Name of the source bucket          |
+-----------------+------------------------------------+
| key             | Key of the object                  |
+-----------------+------------------------------------+
| --out, -o       | local filename. key if not present |
+-----------------+------------------------------------+
| --backend, -b   | Storage backend name               |
+-----------------+------------------------------------+
| --debug, -d     | Activate debug logs (Flag)         |
+-----------------+------------------------------------+
| --config, -c    | Path to your config file           |
+-----------------+------------------------------------+

-  **Usage example**:
   ``lithops storage get -b ibm_cos cloudbucket test.txt``

``lithops storage delete <bucket> <key>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deletes objects from a given bucket.

+-----------------+------------------------------------+
| Parameter       | Description                        |
+=================+====================================+
| bucket          | Name of the source bucket          |
+-----------------+------------------------------------+
| key             | Key of the object. Not mandatory   |
+-----------------+------------------------------------+
| --prefix, -p    | Prefix of the objects to delete    |
+-----------------+------------------------------------+
| --backend, -b   | Storage backend name               |
+-----------------+------------------------------------+
| --debug, -d     | Activate debug logs (Flag)         |
+-----------------+------------------------------------+
| --config, -c    | Path to your config file           |
+-----------------+------------------------------------+

-  **Usage example**:
-  To delete a given
   object:\ ``lithops storage delete -b ibm_cos cloudbucket test.txt``

-  To delete all objects that start with given prefix
   :``lithops storage delete -b ibm_cos cloudbucket -p test/``

-  To delete all the objects (empty the bucket):
   ``lithops storage delete -b ibm_cos cloudbucket``

``lithops storage list <bucket>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lists objects from a given bucket.

+-----------------+---------------------------------+
| Parameter       | Description                     |
+=================+=================================+
| bucket          | Name of the bucket              |
+-----------------+---------------------------------+
| --prefix, -p    | Prefix of the objects to list   |
+-----------------+---------------------------------+
| --backend, -b   | Storage backend name            |
+-----------------+---------------------------------+
| --debug, -d     | Activate debug logs (Flag)      |
+-----------------+---------------------------------+
| --config, -c    | Path to your config file        |
+-----------------+---------------------------------+

-  **Usage example**:
-  To list all the objects in a
   bucket:\ ``lithops storage list -b ibm_cos cloudbucket``

-  To list all objects that start with given prefix
   :``lithops storage list -b ibm_cos cloudbucket -p test/``
