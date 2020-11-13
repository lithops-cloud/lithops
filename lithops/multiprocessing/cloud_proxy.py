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

import io
import os as base_os
from functools import partial
from lithops.storage import Storage
from lithops.utils import is_lithops_worker
from lithops import config


#
# Picklable cloud object storage client
#

class CloudStorage(Storage):
    def __init__(self, storage_config=None, lithops_config=None, storage_backend=None, bucket=None):
        if lithops_config is None:
            self.lithops_config = config.default_config()
        if storage_config is None:
            self.storage_config = config.extract_storage_config(self.lithops_config)
        if storage_backend is None:
            self.storage_backend = self.storage_config['backend']
        if bucket is not None:
            self.storage_config['bucket'] = bucket

        super().__init__(storage_config=self.storage_config,
                         lithops_config=self.lithops_config,
                         storage_backend=self.storage_backend)

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__init__(**state)


class CloudFileProxy:
    def __init__(self, cloud_storage=None):
        self._storage = cloud_storage or CloudStorage()
        self.path = _path(self._storage)

    def __getattr__(self, name):
        # we only reach here if the attr is not defined
        return getattr(base_os, name)

    def open(self, filename, mode='r'):
        return cloud_open(filename, mode=mode, cloud_storage=self._storage)

    def listdir(self, path='', suffix_dirs=False):
        if path == '':
            prefix = path
        else:
            prefix = path if path.endswith('/') else path + '/'

        paths = self._storage.list_keys(prefix=prefix, bucket_name=_storage.bucket)
        names = set()
        for p in paths:
            p = p[len(prefix):] if p.startswith(prefix) else p
            splits = p.split('/')
            name = splits[0] + '/' if suffix_dirs and len(splits) > 1 else splits[0]
            names |= set([name])
        return list(names)

    def walk(self, top, topdown=True, onerror=None, followlinks=False):
        dirs = []
        files = []

        for path in self.listdir(top, suffix_dirs=True):
            if path.endswith('/'):
                dirs.append(path[:-1])
            else:
                files.append(path)

        if dirs == [] and files == [] and not self.path.exists(top):
            raise StopIteration

        elif topdown:
            yield (top, dirs, files)
            for dir in dirs:
                for result in self.walk('/'.join([top, dir]), topdown, onerror, followlinks):
                    yield result

        else:
            for dir in dirs:
                for result in self.walk('/'.join([top, dir]), topdown, onerror, followlinks):
                    yield result
            yield (top, dirs, files)

    def remove(self, key):
        self._storage.delete_cobject(key=key)

    def mkdir(self, *args, **kwargs):
        pass

    def makedirs(self, *args, **kwargs):
        pass


class _path:
    def __init__(self, cloud_storage=None):
        self._storage = cloud_storage or CloudStorage()

    def __getattr__(self, name):
        # we only reach here if the attr is not defined
        return getattr(base_os.path, name)

    def isfile(self, path):
        return path in self._storage.list_keys(prefix=path)

    def isdir(self, path):
        path = path if path.endswith('/') else path + '/'
        for key in self._storage.list_keys(prefix=path):
            if key.startswith(path):
                return True
        return False

    def exists(self, path):
        dirpath = path if path.endswith('/') else path + '/'
        for key in self._storage.list_keys(prefix=path):
            if key.startswith(dirpath) or key == path:
                return True
        return False


class DelayedBytesBuffer(io.BytesIO):
    def __init__(self, action, initial_bytes=None):
        super().__init__(initial_bytes)
        self._action = action

    def close(self):
        self._action(self.getvalue())
        io.BytesIO.close(self)


class DelayedStringBuffer(io.StringIO):
    def __init__(self, action, initial_value=None):
        super().__init__(initial_value)
        self._action = action

    def close(self):
        self._action(data=self.getvalue())
        io.StringIO.close(self)


def cloud_open(filename, mode='r', cloud_storage=None):
    storage = cloud_storage or CloudStorage()
    if 'r' in mode:
        if 'b' in mode:
            # we could get_data(stream=True) but some streams are not seekable
            return io.BytesIO(storage.get_object(bucket_name=storage.bucket, key=filename))
        else:
            return io.StringIO(storage.get_object(bucket_name=storage.bucket, key=filename).decode())

    if 'w' in mode:
        action = partial(storage.put_object, key=filename, bucket_name=storage.bucket)
        if 'b' in mode:
            return DelayedBytesBuffer(action)
        else:
            return DelayedStringBuffer(action)


if not is_lithops_worker():
    try:
        _storage = CloudStorage()
    except FileNotFoundError:
        # should never happen unless we are using
        # this module classes for other purposes
        os = None
        open = None
    else:
        os = CloudFileProxy(_storage)
        open = partial(cloud_open, cloud_storage=_storage)
else:
    # should never be used unless we explicitly import
    # inside a function, which is not a good practice
    os = None
    open = None
