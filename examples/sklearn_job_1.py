"""
Simple Lithops example running a scikit-learn hyperparameter search on
cloud functions, through the joblib backend.

RandomizedSearchCV tries many parameter combinations, and each one is an
independent fit, so joblib hands them out as separate functions.
"""
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
