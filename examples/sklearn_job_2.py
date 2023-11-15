import joblib
from lithops.util.joblib import register_lithops
from sklearn.datasets import load_digits
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV

digits = load_digits()
param_grid = {
    "n_estimators": [100, 50, 25],
}
model = RandomForestClassifier()
search = GridSearchCV(model, param_grid, cv=2, refit=True)


register_lithops()

with joblib.parallel_backend("lithops"):
    search.fit(
        digits.data,
        digits.target,
    )
print("Best score: %0.3f" % search.best_score_)
# print("Best parameters set:")
# # best_parameters = search.best_estimator_.get_params()
# # print(best_parameters)
