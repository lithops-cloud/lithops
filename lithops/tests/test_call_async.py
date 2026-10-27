#
# (C) Copyright IBM Corp. 2020
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pytest
import lithops
import logging
from lithops.tests.functions import (
    SideEffect,
    passthrough_function,
    simple_map_function
)

logger = logging.getLogger(__name__)


class TestCallAsync:

    def test_hello_world(self):
        def hello_world(param):
            return "Hello World!"

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(hello_world, "")
        result = fexec.get_result()
        assert result == "Hello World!"

    def test_lambda_fn(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(lambda x: " ".join(x), ["a", "b"])
        result = fexec.get_result()
        assert result == "a b"

    def test_set_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(simple_map_function, (4, 6))
        result = fexec.get_result()
        assert result == 10

    def test_partial_function(self):
        from functools import partial

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(partial(simple_map_function, 4), 6)
        result = fexec.get_result()
        assert result == 10

    def test_dict_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(simple_map_function, {'x': 2, 'y': 8})
        result = fexec.get_result()
        assert result == 10

    def test_single_future_is_a_chain(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        future = fexec.call_async(lambda x: x + 1, 1)
        fexec.call_async(lambda x: x * 3, future)
        assert fexec.get_result() == 6

    def test_list_of_futures_is_one_chained_call(self):
        """A list used to be passed through as future objects"""
        def double(x):
            return x * 2

        def total(values):
            return sum(values)

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        futures = fexec.map(double, [1, 2, 3])
        chained = fexec.call_async(total, list(futures))
        assert chained.job_id.startswith('A')
        assert fexec.get_result(chained) == 12

    def test_tuple_of_futures_is_one_chained_call(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        first = fexec.call_async(lambda x: x + 1, 1)
        second = fexec.call_async(lambda x: x + 2, 1)
        chained = fexec.call_async(lambda x, y: x * y, (first, second))
        assert fexec.get_result(chained) == 6

    def test_object_with_side_effects(self):
        se = SideEffect()
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(passthrough_function, se)
        result = fexec.get_result()
        assert result == 5
