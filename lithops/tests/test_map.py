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
from lithops.tests.functions import (
    simple_map_function,
    hello_world,
    lithops_inside_lithops_map_function,
    lithops_return_futures_map,
    lithops_return_futures_call_async,
    lithops_return_futures_map_multiple,
    concat
)


class TestMap:

    def test_simple_map(self):
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(simple_map_function, iterdata)
        result = fexec.get_result()
        assert result == [2, 4, 6, 8]

    def test_max_workers(self):
        iterdata = [(1, 1), (2, 2), (3, 3), (4, 4)]
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config, max_workers=1)
        fexec.map(simple_map_function, iterdata)
        result = fexec.get_result()
        assert result == [2, 4, 6, 8]

    def test_range_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        generator_iterdata = range(2)
        fexec.map(hello_world, generator_iterdata)
        result = fexec.get_result()
        assert result == ['Hello World!'] * 2

    def test_dict_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        listDicts_iterdata = [{'x': 2, 'y': 8}, {'x': 2, 'y': 8}]
        fexec.map(simple_map_function, listDicts_iterdata)
        result = fexec.get_result()
        assert result == [10, 10]

    def test_set_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        set_iterdata = [["a", "b"], ["c", "d"]]
        fexec.map(concat, set_iterdata)
        result = fexec.get_result()
        assert result == ["a b", "c d"]

    def test_set_range_iterdata(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        set_iterdata = set(range(2))
        fexec.map(hello_world, set_iterdata)
        result = fexec.get_result()
        assert result == ['Hello World!'] * 2

    def test_multiple_executions(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        iterdata = [(1, 1), (2, 2)]
        fexec.map(simple_map_function, iterdata)
        iterdata = [(3, 3), (4, 4)]
        fexec.map(simple_map_function, iterdata)
        result = fexec.get_result()
        assert result == [2, 4, 6, 8]

        iterdata = [(1, 1), (2, 2)]
        fexec.map(simple_map_function, iterdata)
        result = fexec.get_result()
        assert result == [2, 4]

        iterdata = [(1, 1), (2, 2)]
        futures1 = fexec.map(simple_map_function, iterdata)
        result1 = fexec.get_result(fs=futures1)
        iterdata = [(3, 3), (4, 4)]
        futures2 = fexec.map(simple_map_function, iterdata)
        result2 = fexec.get_result(fs=futures2)
        assert result1 == [2, 4]
        assert result2 == [6, 8]

    def test_lithops_inside_lithops(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.map(lithops_inside_lithops_map_function, range(1, 5))
        result = fexec.get_result()
        assert result == [list(range(i)) for i in range(1, 5)]

    def test_lithops_return_futures_map(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(lithops_return_futures_map, 3)
        result = fexec.get_result()
        assert result == [1, 2, 3]

    def test_lithops_return_futures_call_async(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(lithops_return_futures_call_async, 3)
        result = fexec.get_result()
        assert result == 9

    def test_lithops_return_futures_map_multiple(self):
        fexec = lithops.FunctionExecutor(config=pytest.lithops_config)
        fexec.call_async(lithops_return_futures_map_multiple, 3)
        fexec.wait()
        result = fexec.get_result()
        assert result == [1, 2, 3, 1, 2, 3]
