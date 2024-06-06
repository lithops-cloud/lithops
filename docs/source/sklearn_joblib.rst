Distributed Scikit-learn / Joblib
=================================

Lithops supports running distributed scikit-learn programs by implementing a Lithops backend for joblib using Functions instead of local processes. This makes it easy to scale existing applications that use scikit-learn from a single node to a cluster.

To get started, first install Lithops and the joblib dependencies with:

.. code-block:: bash

   python3 -m pip install lithops[joblib]


Once installed, use ``from lithops.util.joblib import register_lithops`` and run ``register_lithops()``. This will register Lithops as a joblib backend for scikit-learn to use. Then run your original scikit-learn code inside with ``joblib.parallel_backend('lithops')``.

Refer to the official `JobLib <https://joblib.readthedocs.io/en/latest/parallel.html>`_ and `SkLearn <https://scikit-learn.org/stable/user_guide.html>`_ documentation to operate with these libraries.

Examples
--------

- JobLib Lithops backend example

.. code:: python

    import joblib
    from joblib import Parallel, delayed
    from lithops.util.joblib import register_lithops
    from lithops.utils import setup_lithops_logger

    register_lithops()


    def my_function(x):
        print(x)


    setup_lithops_logger('INFO')

    with joblib.parallel_backend('lithops'):
        Parallel()(delayed(my_function)(i) for i in range(10))


- SkLearn example with Lithops as backend for JobLib

.. code:: python

    import numpy as np
    import joblib
    from lithops.util.joblib import register_lithops
    from lithops.utils import setup_lithops_logger
    from sklearn.datasets import load_digits
    from sklearn.model_selection import RandomizedSearchCV
    from sklearn.svm import SVC

    digits = load_digits()
    param_space = {
        'C': np.logspace(-6, 6, 30),
        'gamma': np.logspace(-8, 8, 30),
        'tol': np.logspace(-4, -1, 30),
        'class_weight': [None, 'balanced'],
    }
    model = SVC(kernel='rbf')
    search = RandomizedSearchCV(model, param_space, cv=2, n_iter=50, verbose=10)


    register_lithops()

    setup_lithops_logger('INFO')

    with joblib.parallel_backend('lithops'):
        search.fit(digits.data, digits.target)


