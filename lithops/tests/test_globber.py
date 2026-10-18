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

import os

import pytest

from lithops.libs.globber import match


@pytest.fixture(params=['/', '\\'], ids=['posix', 'windows'])
def platform_sep(request, monkeypatch):
    """Runs a test with the separator of POSIX and of Windows"""
    monkeypatch.setattr(os, 'sep', request.param)
    return request.param


class TestGlobberMatch:

    @pytest.mark.parametrize('pattern, file_name, matches', [
        ('dir/*.csv', 'dir/a.csv', True),
        ('dir/*.csv', 'dir/sub/a.csv', False),
        ('dir/?.csv', 'dir/a.csv', True),
        ('dir/?.csv', 'dir/ab.csv', False),
        ('dir/**/*.csv', 'dir/a.csv', True),
        ('dir/**/*.csv', 'dir/sub/deeper/a.csv', True),
        ('**', 'dir/sub/a.csv', True),
        ('dir/\\*.csv', 'dir/*.csv', True),
        ('dir/\\*.csv', 'dir/a.csv', False),
        ('dir/[a].csv', 'dir/[a].csv', True),
        ('dir/[a].csv', 'dir/a.csv', False),
        # the trailing '/' of a folder marker is ignored
        ('dir/*', 'dir/sub/', True),
    ])
    def test_object_keys(self, platform_sep, pattern, file_name, matches):
        """Keys are split on '/' on every platform: on Windows none matched"""
        assert match(pattern, file_name) is matches

    def test_backslash_is_not_a_separator(self, platform_sep):
        assert match('dir/*', 'dir/a\\b.csv')
        assert not match('dir/a/*', 'dir/a\\b.csv')

    @pytest.mark.parametrize('pattern', ['a**', '**a', 'dir/a**/b'])
    def test_double_star_not_alone(self, pattern):
        with pytest.raises(ValueError, match='not alone'):
            match(pattern, 'a')
