# Distributed Scikit-learn / Joblib (beta)

lithops supports running distributed scikit-learn programs by implementing a Lithops backend for joblib using Functions instead of local processes. This makes it easy to scale existing applications that use scikit-learn from a single node to a cluster.

*Note:* This API is **beta** and may be revised in future releases. If you encounter any bugs, please open an issue on GitHub.

## Quickstart
To get started, first install Lithops, then use from lithops.util.joblib import register_lithops and run register_lithops(). This will register Lithops as a joblib backend for scikit-learn to use. Then run your original scikit-learn code inside with joblib.parallel_backend('lithops').

- Find a simple joblib example in [examples/joblib_backend.py](../examples/joblib_backend.py)
- Find a simple sklearn example in [examples/sklearn_job.py](../examples/sklearn_job.py)

Refer to the official [joblib](https://joblib.readthedocs.io/en/latest/parallel.html) and [sklearn](https://scikit-learn.org/stable/user_guide.html) documentation to operate with these libraries.
