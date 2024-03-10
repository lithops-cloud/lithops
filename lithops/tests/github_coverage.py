#
# (C) Copyright Cloudlab URV 2024
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

from lithops.tests.tests_main import run_tests
from lithops.scripts.cli import runtime, lithops_cli

def test_github_localhost():
    run_tests("all", None, "", None, None,
                  None, False, False)

def test_github_k8s():
    runtime(['build', 'acanadilla/k8s_internal', '--file', './runtime/kubernetes/Dockerfile', '--backend', 'k8s'], standalone_mode=False)
    run_tests("", None, "call_async", None, None,
                  None, False, False)
    run_tests("", None, "storage", None, None,
                  None, False, False)
    run_tests("", None, "map_reduce", None, None,
                  None, False, False)
    runtime(['build', 'acanadilla/test-bucket-k8s', '--file', './runtime/kubernetes/Dockerfile', '--backend', 'k8s'], standalone_mode=False)
    runtime(['deploy', 'acanadilla/test-bucket-k8s', '--memory', 500], standalone_mode=False)
    runtime(['list'], standalone_mode=False)
    lithops_cli(['clean'], standalone_mode=False)

def test_github_aws():
    run_tests("all", None, "", None, None,
                  None, False, False)
    runtime(['build', 'acanadilla/test-bucket-s3', '--file', './runtime/aws_lambda/Dockerfile', '--backend', 'aws_lambda'], standalone_mode=False)
    runtime(['deploy', 'acanadilla/test-bucket-s3', '--memory', 500], standalone_mode=False)
    runtime(['list'], standalone_mode=False)
    lithops_cli(['clean'], standalone_mode=False)
