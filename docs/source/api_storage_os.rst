Storage OS API
==============

Lithops provides a transparent way to interact with the storage backend.

The module ``lithops.storage.cloud_proxy`` mimics the ``os`` and the
built-in function ``open`` to access Cloud Storage as if it were a local
file system.

By default, the configuration is loaded from the lithops config file, so
there is no need to provide any parameter to use ``cloud_proxy``:

.. code:: python

    from lithops.storage.cloud_proxy import os, open

    with open('dir/file.txt', 'r') as f:
        content = f.read()

Alternatively, you can instantiate a CloudFileProxy with different
lithops configuration through a dictionary. In this case, it will load
the storage backend set in the ``storage`` key of the ``lithops``
section:

.. code:: python

    from lithops.storage.cloud_proxy import CloudStorage, CloudFileProxy

    config = {'lithops' : {'storage_config' : 'ibm_cos'},
              'ibm_cos': {'region': 'REGION', 'api_key': 'API_KEY'}}

    cloud_storage = CloudStorage(config)
    cloud_file_proxy = CloudFileProxy(cloud_storage)

    with cloud_file_proxy.open('dir/file.txt', 'r') as f:
        content = f.read()

Cloud Proxy Storage API
-----------------------

``open()``
~~~~~~~~~~

Similar to Python's built-in function `open() <https://docs.python.org/3/library/functions.html#open>`__.

Manipulate an object stored in Cloud Object Storage.

+-------------+-------------------------------------------------------------------------------------------------------------------+
| Parameter   | Description                                                                                                       |
+=============+===================================================================================================================+
| file        | File path. Must be an absolute path.                                                                              |
+-------------+-------------------------------------------------------------------------------------------------------------------+
| mode        | Specify the mode in which the file is opened (``'r'`` for read and ``'w'`` for write text, ``'b'`` for binary).   |
+-------------+-------------------------------------------------------------------------------------------------------------------+

.. code:: python

   with open('bar/foo.txt', 'w') as f:
       f.write('Hello world!')


``os``
~~~~~~

Similar to Python's `os <https://docs.python.org/3/library/os.html>`__ library, except only file-related functionalities are implemented.

``os.listdir``
^^^^^^^^^^^^^^

List all objects located in a directory.

+--------------+--------------------------------------+---------+
| Parameter    | Description                          | Default |
+==============+======================================+=========+
| path         | File path. Must be an absolute path. |         |
+--------------+--------------------------------------+---------+
| suffix\_dirs | Append a slash to directories listes | False   |
+--------------+--------------------------------------+---------+

.. code:: python

    with open('bar/foo.txt', 'w') as f:
        f.write('Hello world!')

    files = os.listdir('/bar') 
    print(files)  # Prints ['foo.txt']

``os.walk``
^^^^^^^^^^^

List recursively all files and directories in a root path.

+-----------+---------------------------------------------------+---------+
| Parameter | Description                                       | Default |
+===========+===================================================+=========+
| path      | Root path. Must be an absolute path.              |         |
+-----------+---------------------------------------------------+---------+
| topdown   | List directory tree top-down instead of bottom-up | True    |
+-----------+---------------------------------------------------+---------+

.. code:: python

    files = ['/bar/foo.txt', '/bar/image.jpg', '/bar/subdir/data.csv']
    for file in files:
        with open(file, 'w') as f:
            f.write('Hello world!')

    for root, dirs, files in os.walk('/'): 
        print(root, dirs, files)  # Prints '/' ['bar'] [], '/bar' ['subdir'] ['foo.txt', 'image.jpg'], '/bar/subdir' [] ['data.csv']

``os.remove``
^^^^^^^^^^^^^

Delete a file. If the directory where the file is located is empty after
the file is deleted, this directory it is also removed.

+-----------+--------------------------------------+---------+
| Parameter | Description                          | Default |
+===========+======================================+=========+
| path      | File path. Must be an absolute path. |         |
+-----------+--------------------------------------+---------+

.. code:: python

    with open('bar/foo.txt', 'w') as f:
        f.write('Hello world!')

    os.remove('/bar/foo.txt')
    files = os.listdir('/')
    print(files)  # Prints []


``os.path``
~~~~~~~~~~~

Similar to Python's `os.path <https://docs.python.org/3/library/os.path.html>`__, except only file-realted functionalities are implemented.

``os.path.isfile``
^^^^^^^^^^^^^^^^^^

Return ``True`` if a path is a file.

+-----------+--------------------------------------+---------+
| Parameter | Description                          | Default |
+===========+======================================+=========+
| path      | File path. Must be an absolute path. |         |
+-----------+--------------------------------------+---------+

.. code:: python

    with open('bar/foo.txt', 'w') as f:
        f.write('Hello world!')

    print(os.path.isfile('/bar/foo.txt'))  # Prints ``True``
    print(os.path.isfile('/bar'))  # Prints ``False``

``os.path.isdir``
^^^^^^^^^^^^^^^^^

Return ``True`` if a path is a directory.

+-----------+-------------------------------------------+---------+
| Parameter | Description                               | Default |
+===========+===========================================+=========+
| path      | Directory path. Must be an absolute path. |         |
+-----------+-------------------------------------------+---------+

.. code:: python

    with open('bar/foo.txt', 'w') as f:
        f.write('Hello world!')

    print(os.path.isdir('/bar/foo.txt'))  # Prints False
    print(os.path.isdir('/bar'))  # Prints True

``os.path.exists``
^^^^^^^^^^^^^^^^^^

Retrun ``True`` if a path corresponds to an existing file or directory
in Cloud Object Storage.

+-----------+----------------------------------------+---------+
| Parameter | Description                            | Default |
+===========+========================================+=========+
| path      | Target path. Must be an absolute path. |         |
+-----------+----------------------------------------+---------+

.. code:: python

    with open('bar/foo.txt', 'w') as f:
        f.write('Hello world!')

    print(os.path.exists('/bar/foo.txt'))  # Prints True
    print(os.path.exists('/baz/foo.txt'))  # Prints False
