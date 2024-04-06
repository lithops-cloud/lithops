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
from lithops.tests.functions import simple_map_function, SideEffect, passthrough_function

logger = logging.getLogger(__name__)


class TestAsync:

    def test_call_async(self):
        def hello_world(param):
            return "Hello World!"

        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(hello_world, "")
        result = fexec.get_result()
        assert result == "Hello World!"

    def test_call_async_lambda_fn(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(lambda x: " ".join(x), ["a", "b"])
        result = fexec.get_result()
        assert result == "a b"

    def test_call_async_set_params(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(simple_map_function, (4, 6))
        result = fexec.get_result()
        assert result == 10

    def test_call_async_dict_params(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(simple_map_function, {'x': 2, 'y': 8})
        result = fexec.get_result()
        assert result == 10

    def test_call_async_object_with_side_effects(self):
        """Test that passing an object with properties that trigger side effects does not cause the side effects to be triggered."""
            
        se = SideEffect()
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(passthrough_function, se)
        result = fexec.get_result()
