import pytest

import lithops


class HasAmbiguousTruthValue:
    """An object with an ambiguous truth value, simulates pandas.DataFrame and numpy.NDArray."""

    def __init__(self, data):
        self.data = data

    def __bool__(self):
        raise ValueError(
            f"The truth value of a {type(self).__name__} is ambiguous. "
            "Use a.empty, a.bool(), a.item(), a.any() or a.all()."
        )


def test_fn_returns_obj_with_ambiguous_truth_value():
    def returns_obj_with_ambiguous_truth_value(param):
        return HasAmbiguousTruthValue(param)

    fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
    future = fexec.call_async(returns_obj_with_ambiguous_truth_value, "Hello World!")
    result = future.result()
    assert result.data == "Hello World!"
