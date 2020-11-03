#
# Copyright Cloudlab URV 2020
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

from lithops import FunctionExecutor
from lithops.wait import ALL_COMPLETED, ALWAYS

from . import util

__all__ = ['Popen']


#
# Start child process using cloud
#

class Popen(object):
    method = 'cloud'

    def __init__(self, process_obj):
        util._flush_std_streams()
        self.returncode = None
        self._executor = FunctionExecutor()
        self._launch(process_obj)

    def duplicate_for_child(self, fd):
        return fd

    def poll(self, flag=ALWAYS):
        if self.returncode is None:
            self._executor.wait([self.sentinel], return_when=flag)
            if self.sentinel.ready or self.sentinel.done:
                self.returncode = 0
            if self.sentinel.error:
                self.returncode = 1
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            wait = self._executor.wait
            if not wait([self.sentinel], timeout=timeout):
                return None
            # This shouldn't block if wait() returned successfully.
            return self.poll(ALWAYS if timeout == 0.0 else ALL_COMPLETED)
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            try:
                self.sentinel.cancel()
            except NotImplementedError:
                pass

    def _launch(self, process_obj):
        fn_args = [*process_obj._args, *process_obj._kwargs]
        self.sentinel = self._executor.call_async(process_obj._target, fn_args)
