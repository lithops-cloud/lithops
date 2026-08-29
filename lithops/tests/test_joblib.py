#
# Live tests of the joblib backend, which is what the examples in examples/
# use to run scikit-learn searches on Lithops.
#
# These run real jobs, so every class skips unless the packages it needs are
# installed, and they pin themselves to the localhost backend: they are here
# to exercise the joblib integration, not to spend money on a cloud one.
#

import pytest

joblib = pytest.importorskip('joblib')
pytest.importorskip('diskcache')
pytest.importorskip('numpy')

from lithops.multiprocessing import config as mp_config  # noqa: E402
from lithops.util.joblib import register_lithops  # noqa: E402

LOCALHOST_ARGS = {'backend': 'localhost', 'storage': 'localhost'}


@pytest.fixture(autouse=True)
def lithops_joblib_backend():
    """
    Registers the backend and gives lithops.multiprocessing its parameters
    back afterwards, as they are process-wide
    """
    register_lithops()
    saved = mp_config.get_parameter(mp_config.LITHOPS_CONFIG)
    yield
    mp_config.set_parameter(mp_config.LITHOPS_CONFIG, saved)


def double(x):
    return x * 2


def _on_localhost(**extra):
    # n_jobs has to be given: parallel_config leaves it at 1, and joblib runs
    # a single job inline without ever asking the backend, unlike the
    # parallel_backend the examples use, which defaults it to -1.
    #
    # A number rather than -1, because -1 asks lithops.multiprocessing for a
    # cpu_count, and that reads the default configuration of the machine
    # instead of the one these tests pin
    extra.setdefault('n_jobs', 4)
    return joblib.parallel_config(
        backend='lithops', lithops_args=LOCALHOST_ARGS, **extra
    )


def _counting_optimizer(collected):
    """
    Wraps the shared-object optimizer to record how many calls of each batch
    had arguments replaced, which is proof the batch went through Lithops
    """
    from lithops.util.joblib import lithops_backend

    real_find = lithops_backend.find_shared_objects

    def counting_find(calls):
        out = real_find(calls)
        collected.append(sum(1 for call in out if len(call) > 3))
        return out

    return counting_find


class TestJoblibBackendLive:

    def test_parallel_over_the_lithops_backend(self):
        from unittest.mock import patch

        from lithops.util.joblib import lithops_backend

        batches = []
        with patch.object(
            lithops_backend, 'find_shared_objects',
            _counting_optimizer(batches)
        ):
            with _on_localhost():
                results = joblib.Parallel()(
                    joblib.delayed(double)(i) for i in range(4)
                )
        assert results == [0, 2, 4, 6]
        # Without this the test would pass on joblib running it inline
        assert batches, 'the calls never went through the Lithops backend'

    def test_parallel_with_threads_preferred(self):
        # One task runs the whole batch, each call in a thread of its own
        with _on_localhost(prefer='threads'):
            results = joblib.Parallel()(
                joblib.delayed(double)(i) for i in range(3)
            )
        assert results == [0, 2, 4]

    def test_an_exception_in_a_call_reaches_the_caller(self):
        with _on_localhost():
            with pytest.raises(ZeroDivisionError):
                joblib.Parallel()(
                    joblib.delayed(_divide)(1, d) for d in (1, 0)
                )

    def test_the_shared_argument_travels_once(self):
        # What the backend exists for: the same list is an argument of every
        # call, so it goes to storage once and the calls carry a reference
        import numpy as np

        shared = np.arange(64)
        with _on_localhost():
            results = joblib.Parallel()(
                joblib.delayed(_sum_with)(shared, i) for i in range(4)
            )
        assert results == [int(shared.sum()) + i for i in range(4)]

    def test_lithops_args_pins_the_backend(self):
        with _on_localhost():
            assert mp_config.get_parameter(mp_config.LITHOPS_CONFIG) == (
                LOCALHOST_ARGS
            )


def _divide(a, b):
    return a / b


def _sum_with(shared, i):
    return int(shared.sum()) + i


def _tiny_classification_data(n=40, n_features=8, n_classes=3):
    """
    A small labelled set for the sklearn searches. load_digits() assigns
    to ndarray.shape, which NumPy 2.5 warns on
    """
    import numpy as np

    rng = np.random.default_rng(0)
    return (
        rng.normal(size=(n, n_features)),
        rng.integers(0, n_classes, size=n),
    )


class TestSklearnOverJoblib:
    """
    The searches the examples in examples/ run, in a smaller shape so that
    they finish in seconds on the localhost backend
    """

    @pytest.fixture(autouse=True)
    def _needs_sklearn(self):
        pytest.importorskip('sklearn')

    def test_grid_search_over_the_lithops_backend(self):
        from sklearn.model_selection import GridSearchCV
        from sklearn.tree import DecisionTreeClassifier

        X, y = _tiny_classification_data()
        search = GridSearchCV(
            DecisionTreeClassifier(random_state=0),
            {'max_depth': [2, 4]},
            cv=2,
            refit=True,
        )

        with _on_localhost():
            search.fit(X, y)

        assert search.best_params_['max_depth'] in (2, 4)
        assert 0.0 < search.best_score_ <= 1.0
        # refit ran, so the search can predict
        assert len(search.predict(X[:5])) == 5

    def test_the_dataset_is_proxied_for_every_fit_of_the_search(self):
        # Every fit gets the same X and y, so they travel as one cloud object
        # instead of once per task. A call whose arguments were replaced
        # carries a fourth element with their positions
        from unittest.mock import patch

        from sklearn.model_selection import GridSearchCV
        from sklearn.tree import DecisionTreeClassifier

        from lithops.util.joblib import lithops_backend

        X, y = _tiny_classification_data()
        search = GridSearchCV(
            DecisionTreeClassifier(random_state=0),
            {'max_depth': [2, 4, 6]},
            cv=2,
        )

        proxied = []
        with patch.object(
            lithops_backend, 'find_shared_objects',
            _counting_optimizer(proxied)
        ):
            with _on_localhost():
                search.fit(X, y)

        assert proxied, 'the batch never went through the optimizer'
        # Three candidates over two folds
        assert max(proxied) >= 6

    def test_randomized_search_over_the_lithops_backend(self):
        import numpy as np
        from sklearn.model_selection import RandomizedSearchCV
        from sklearn.tree import DecisionTreeClassifier

        X, y = _tiny_classification_data()
        search = RandomizedSearchCV(
            DecisionTreeClassifier(random_state=0),
            {'min_samples_leaf': np.arange(1, 10)},
            cv=2,
            n_iter=3,
            random_state=0,
        )

        with _on_localhost():
            search.fit(X, y)

        assert 0.0 < search.best_score_ <= 1.0

    def test_a_pipeline_search_over_the_lithops_backend(self):
        # The shape of examples/sklearn_job_3.py, without pandas
        from sklearn.model_selection import GridSearchCV
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.tree import DecisionTreeClassifier

        X, y = _tiny_classification_data()
        pipeline = Pipeline([
            ('scale', StandardScaler()),
            ('classifier', DecisionTreeClassifier(random_state=0)),
        ])
        search = GridSearchCV(
            pipeline, {'classifier__max_depth': [2, 4]}, cv=2, refit=True
        )

        with _on_localhost():
            search.fit(X, y)

        assert search.best_params_['classifier__max_depth'] in (2, 4)
        assert 0.0 < search.best_score_ <= 1.0
