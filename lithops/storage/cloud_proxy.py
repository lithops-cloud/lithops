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
from typing import Any, Dict, Iterable, List, Optional, Union

from lithops.storage import Storage
from lithops.utils import is_lithops_worker
from lithops.config import (
    default_storage_config,
    load_yaml_config,
    extract_storage_config,
)
from lithops.constants import (
    JOBS_PREFIX, TEMP_PREFIX, LOGS_PREFIX, RUNTIMES_PREFIX,
)


_LITHOPS_PREFIXES = (JOBS_PREFIX, TEMP_PREFIX, LOGS_PREFIX, RUNTIMES_PREFIX)


def remove_lithops_keys(keys: Iterable[str]) -> List[str]:
    """
    Drops the keys Lithops itself writes, so that the proxy only shows the
    data of the user
    """
    return [key for key in keys if not key.startswith(_LITHOPS_PREFIXES)]


def _to_key(path, as_dir=False):
    """
    Turns a path into the key, or key prefix, that matches it: keys have no
    leading slash, and a trailing one is added when only the contents of a
    directory should match
    """
    key = path[1:] if path.startswith('/') else path
    if as_dir and key != '' and not key.endswith('/'):
        key = key + '/'
    return key


#
# Picklable cloud object storage client
#

class CloudStorage(Storage):
    """
    Storage client that can be pickled, so that it can travel to a worker.
    It keeps the configuration it was built from and builds a new client on
    the other side, as the underlying backend clients are not picklable
    """

    def __init__(self, config: Optional[Union[str, Dict[str, Any]]] = None):
        if isinstance(config, str):
            config = load_yaml_config(config)
            self._config = extract_storage_config(config)
        elif isinstance(config, dict) and 'lithops' in config:
            self._config = extract_storage_config(config)
        elif isinstance(config, dict):
            self._config = config
        else:
            self._config = extract_storage_config(default_storage_config())
        super().__init__(storage_config=self._config)

    def __getstate__(self):
        return self._config

    def __setstate__(self, state):
        self.__init__(state)

    def put_data(self, key, data):
        """Writes an object in the configured bucket"""
        return self.put_object(self.bucket, key, data)

    def get_data(self, key):
        """Reads an object from the configured bucket"""
        return self.get_object(self.bucket, key)

    def delete_data(self, key):
        """Deletes an object from the configured bucket"""
        self.delete_object(self.bucket, key)

    def list_bucket_keys(self, prefix=None):
        """Lists the keys of the configured bucket"""
        return self.list_keys(self.bucket, prefix)


class CloudFileProxy:
    """
    Stand-in for the os module that reads and writes objects in storage
    instead of files. Anything it does not implement is served by os itself
    """

    def __init__(self, cloud_storage: Optional[CloudStorage] = None):
        self._storage = cloud_storage or CloudStorage()
        self.path = _path(self._storage)

    def __getattr__(self, name):
        # we only reach here if the attr is not defined
        return getattr(base_os, name)

    def open(self, filename, mode='r'):
        """Opens an object as a file-like buffer"""
        return cloud_open(filename, mode=mode, cloud_storage=self._storage)

    def listdir(self, path='', suffix_dirs=False):
        """
        Lists the names directly under a path, as os.listdir does. Keys are
        flat in storage, so a name is the first segment left after the prefix,
        and the ones that stand for a directory can be marked with a slash
        """
        prefix = _to_key(path, as_dir=True)

        names = set()
        for p in remove_lithops_keys(self._storage.list_bucket_keys(prefix=prefix)):
            p = p[len(prefix):] if p.startswith(prefix) else p
            if p.startswith('/'):
                p = p[1:]
            splits = p.split('/')
            name = (
                splits[0] + '/' if suffix_dirs and len(splits) > 1
                else splits[0]
            )
            names.add(name)
        return list(names)

    def _walk_children(self, top, dirs, topdown, onerror, followlinks):
        """Walks each subdirectory of a path, in the requested order"""
        for dir_name in dirs:
            yield from self.walk(
                base_os.path.join(top, dir_name),
                topdown, onerror, followlinks,
            )

    def walk(self, top, topdown=True, onerror=None, followlinks=False):
        """
        Walks a path yielding (top, dirs, files), as os.walk does, and yields
        nothing at all when the path holds no key
        """
        dirs = []
        files = []

        for path in self.listdir(top, suffix_dirs=True):
            if path.endswith('/'):
                dirs.append(path[:-1])
            else:
                files.append(path)

        if dirs == [] and files == [] and not self.path.exists(top):
            return
        if topdown:
            yield top, dirs, files
            yield from self._walk_children(
                top, dirs, topdown, onerror, followlinks
            )
        else:
            yield from self._walk_children(
                top, dirs, topdown, onerror, followlinks
            )
            yield top, dirs, files

    def remove(self, path):
        """Deletes the object a path names"""
        self._storage.delete_data(_to_key(path))

    def mkdir(self, *args, **kwargs):
        """Does nothing: storage has no directories to create"""
        pass

    def makedirs(self, *args, **kwargs):
        """Does nothing: storage has no directories to create"""
        pass


class _path:
    """
    Stand-in for os.path that answers from the keys in the bucket. Anything
    it does not implement is served by os.path itself
    """

    def __init__(self, cloud_storage: Optional[CloudStorage] = None):
        self._storage = cloud_storage or CloudStorage()

    def __getattr__(self, name):
        # we only reach here if the attr is not defined
        return getattr(base_os.path, name)

    def isfile(self, path):
        """True when the path names an object"""
        key = _to_key(path)
        keys = remove_lithops_keys(
            self._storage.list_bucket_keys(prefix=key)
        )
        return key != '' and key in keys

    def isdir(self, path):
        """True when there is at least one object under the path"""
        prefix = _to_key(path, as_dir=True)
        keys = remove_lithops_keys(
            self._storage.list_bucket_keys(prefix=prefix)
        )
        return bool(keys)

    def exists(self, path):
        """True when the path names an object or a directory holding one"""
        if path == '':
            return False
        key = _to_key(path)
        dirpath = _to_key(path, as_dir=True)
        for k in self._storage.list_bucket_keys(prefix=key):
            if k.startswith(dirpath) or k == key:
                return True
        return False


class _DelayedClose:
    """
    Buffer that runs its action on close, which is what makes a write to
    storage happen only once the caller is done writing
    """

    def close(self):
        # Closing again is a no-op, as for a file, and the buffer stays open
        # if the upload fails so that it can be retried
        if self.closed:
            return
        self._action(self.getvalue())
        super().close()


class DelayedBytesBuffer(_DelayedClose, io.BytesIO):
    """Binary buffer that uploads what it holds when it is closed"""

    def __init__(self, action, initial_bytes=None):
        super().__init__(initial_bytes)
        self._action = action


class DelayedStringBuffer(_DelayedClose, io.StringIO):
    """Text buffer that uploads what it holds when it is closed"""

    def __init__(self, action, initial_value=None):
        super().__init__(initial_value)
        self._action = action


def cloud_open(filename, mode='r', cloud_storage=None):
    """
    Opens an object as a file-like buffer. Reading brings the whole object
    into memory, and writing uploads it when the buffer is closed. With
    'r+' the buffer starts with the object, as a file does, and is uploaded
    on close
    """
    storage = cloud_storage or CloudStorage()
    key = _to_key(filename)
    if 'r' in mode:
        data = storage.get_data(key)
        if '+' in mode:
            action = partial(storage.put_data, key)
            if 'b' in mode:
                return DelayedBytesBuffer(action, data)
            return DelayedStringBuffer(action, data.decode())
        if 'b' in mode:
            # we could get_data(stream=True) but some streams are not seekable
            return io.BytesIO(data)
        return io.StringIO(data.decode())

    if 'w' in mode:
        action = partial(storage.put_data, key)
        if 'b' in mode:
            return DelayedBytesBuffer(action)
        return DelayedStringBuffer(action)

    raise ValueError(f"Unsupported mode '{mode}': only 'r', 'w' and their '+' and 'b' forms are")


def __getattr__(name):
    """
    Builds the ``os`` and ``open`` stand-ins the first time one is read.

    Building them while this module was imported reached the default storage
    backend from the import itself, so a backend that is not configured, not
    installed or not reachable broke ``import`` for everything defined here.
    Whatever the backend has to say is now raised where the stand-in is
    asked for, rather than turning into a ``None`` that fails later on
    """
    if name not in ('os', 'open'):
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

    if is_lithops_worker():
        # should never be used unless we explicitly import
        # inside a function, which is not a good practice
        value = None
    else:
        storage = CloudStorage()
        value = (
            CloudFileProxy(storage) if name == 'os'
            else partial(cloud_open, cloud_storage=storage)
        )

    globals()[name] = value
    return value
