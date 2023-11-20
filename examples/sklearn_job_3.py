import joblib
import pandas as pd
from lithops.util.joblib import register_lithops
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import FunctionTransformer, Pipeline

data = pd.DataFrame(
    {"id": [1, 2, 3, 4, 5, 6], "features": [[1, 2, 3, 4, 5] for _ in range(6)]}
)

target = pd.Series([0, 1, 0, 1, 0, 1])
param_grid = {
    "classifier__n_estimators": [100, 50, 25],
}

# Expands nested columns
format_transformer = FunctionTransformer(lambda df: df.features.apply(pd.Series))

pipeline = Pipeline(
    [
        ("format", format_transformer),
        ("classifier", RandomForestClassifier()),
    ]
)
search = GridSearchCV(pipeline, param_grid, cv=2, refit=True)


register_lithops()
with joblib.parallel_backend("lithops"):
    search.fit(
        data,
        target,
    )

print("Best CV score: %0.3f" % search.best_score_)
print("Best parameters set:")
print(search.best_params_)
