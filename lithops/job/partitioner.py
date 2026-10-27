#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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
import re
import errno
import posixpath
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from lithops import utils
from lithops.storage import Storage
from lithops.storage.utils import CloudObject, CloudObjectUrl, CloudObjectLocal
from lithops.utils import sizeof_fmt

logger = logging.getLogger(__name__)

#: A local path on Windows, where nothing starts with a separator: a drive
#: letter followed by one, or a UNC share. The separator is required, so
#: that a storage key is not read as a path just for holding a colon
_WINDOWS_PATH = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\)')

CHUNK_THRESHOLD = 128 * 1024  # 128KB

# One entry of the map iterdata, and the partitions it was split into
Entry = Dict[str, Any]
Partitions = Tuple[List[Entry], int]


def create_partitions(
    config: Dict[str, Any],
    internal_storage: Any,
    map_iterdata: List[Entry],
    obj_chunk_size: Optional[int],
    obj_chunk_number: Optional[int],
    obj_newline: Optional[str]
) -> Tuple[List[Entry], List[int]]:
    """
    Splits the objects referenced by the iterdata into partitions, one task
    each. Only one kind of source is partitioned per call
    """
    # Partitions made by an earlier call are taken as they are: the retrying
    # executor makes them before invoking, so that each call has an input of
    # its own to resubmit, and partitioning them again would cost a request
    # per object to learn the sizes they already carry
    if map_iterdata and all(_is_partition(elem['obj']) for elem in map_iterdata):
        parts_per_object = [
            elem['obj'].total_parts for elem in map_iterdata if elem['obj'].part == 1
        ]
        return map_iterdata, parts_per_object

    urls = []
    paths = []
    objects = []

    logger.debug("Parsing input data")

    for elem in map_iterdata:
        obj = str(elem['obj'])
        if obj.startswith('http'):
            urls.append(elem)
        elif obj.startswith('/') or _WINDOWS_PATH.match(obj):
            paths.append(elem)
        else:
            objects.append(elem)

    if urls:
        return _split_objects_from_urls(
            urls, obj_chunk_size, obj_chunk_number, obj_newline
        )
    if paths:
        return _split_objects_from_paths(
            paths, obj_chunk_size, obj_chunk_number, obj_newline
        )
    if objects:
        return _split_objects_from_object_storage(
            objects, obj_chunk_size, obj_chunk_number,
            internal_storage, config, obj_newline
        )
    return [], []


def _is_partition(obj: Any) -> bool:
    """Whether an object is one of the partitions _build_partitions() makes"""
    return hasattr(obj, 'data_byte_range') and hasattr(obj, 'total_parts')


def _log_chunk_settings(chunk_size: Optional[int], chunk_number: Optional[int]) -> None:
    if chunk_number:
        logger.debug(f'Chunk number set to {chunk_number}')
    elif chunk_size:
        logger.debug(f'Chunk size set to {chunk_size}')
    else:
        logger.debug('Chunk size and chunk number not set')


def _chunk_sizes(
    obj_size: int,
    chunk_size: Optional[int],
    chunk_number: Optional[int],
    min_chunk: int
) -> List[int]:
    """
    The size of every chunk of one object. A requested chunk number wins over
    a requested chunk size, and an unset one means a single chunk. An object
    of fewer than chunk_number * min_chunk bytes gets fewer chunks, none of
    them under min_chunk bytes
    """
    if chunk_number:
        chunk_number = max(1, min(chunk_number, obj_size // min_chunk))
        bounds = [i * obj_size // chunk_number for i in range(chunk_number + 1)]
        return [end - start for start, end in zip(bounds, bounds[1:])]
    chunk_size = max(chunk_size or obj_size, min_chunk)
    return [chunk_size] * (obj_size // chunk_size + (obj_size % chunk_size > 0))


def _build_partitions(
    entry: Entry,
    make_obj: Callable[[], Any],
    obj_size: Optional[int],
    chunk_size: Optional[int],
    chunk_number: Optional[int],
    obj_newline: Optional[str],
    label: str
) -> Partitions:
    """
    Splits one object into as many partitions as its chunk size or number
    calls for, each one a copy of the entry carrying its own byte range
    """
    if not obj_size:
        return [], 0

    obj_partitions = []
    size = obj_total_partitions = 0
    # Every chunk but the first one starts as many bytes early as the newline
    # has. Longer than the newline, only the first chunk starts at byte 0
    newline_len = len(obj_newline.encode()) if obj_newline is not None else 0
    chunk_sizes = _chunk_sizes(obj_size, chunk_size, chunk_number, newline_len + 1)

    logger.debug(
        f'Creating {len(chunk_sizes)} partitions from {label} ({sizeof_fmt(obj_size)})'
    )

    for obj_chunk_size in chunk_sizes:
        if obj_size <= obj_chunk_size:
            # A single partition reads the whole object, no range needed
            brange = None
            obj_chunk_size = obj_size
        elif obj_newline is None:
            brange = (size, size + obj_chunk_size - 1)
        elif size + obj_chunk_size < obj_size:
            # Records must not be cut in two: a partition starts a newline
            # early to see whether it begins mid record, and overshoots by
            # CHUNK_THRESHOLD so that it can finish the last record it reads
            brange = (
                size - newline_len if size > 0 else 0,
                size + obj_chunk_size + CHUNK_THRESHOLD
            )
        else:
            brange = (size - newline_len, obj_size - 1)
            obj_chunk_size = obj_size - size

        obj_total_partitions += 1

        partition = entry.copy()
        partition['obj'] = make_obj()
        partition['obj'].data_byte_range = brange
        partition['obj'].chunk_size = obj_chunk_size
        partition['obj'].part = obj_total_partitions
        partition['obj'].newline = obj_newline
        partition['obj'].total_size = obj_size
        obj_partitions.append(partition)

        size += obj_chunk_size

    # Only known once the loop is over, so it is filled in afterwards
    for partition in obj_partitions:
        partition['obj'].total_parts = obj_total_partitions

    return obj_partitions, obj_total_partitions


def _collect_partitions(
    split_fn: Callable[[Entry], Partitions],
    entries: List[Entry]
) -> Tuple[List[Entry], List[int]]:
    """
    Splits every entry in parallel, since sizing an object needs a request
    """
    partitions = []
    parts_per_object = []
    with ThreadPoolExecutor(64) as ex:
        for obj_partitions, nparts in ex.map(split_fn, entries):
            partitions.extend(obj_partitions)
            parts_per_object.append(nparts)
    return partitions, parts_per_object


def _split_objects_from_urls(
    map_func_args_list: List[Entry],
    chunk_size: Optional[int],
    chunk_number: Optional[int],
    obj_newline: Optional[str]
) -> Tuple[List[Entry], List[int]]:
    """
    Creates partitions from a list of object URLs
    """
    _log_chunk_settings(chunk_size, chunk_number)

    def _split(entry):
        obj_size = None
        object_url = entry['obj']
        # The worker reads the object with a GET, which follows redirects
        metadata = requests.head(object_url, allow_redirects=True)
        if not 200 <= metadata.status_code < 300:
            raise requests.HTTPError(
                f'HEAD {object_url} returned HTTP {metadata.status_code}, '
                'so its size is unknown', response=metadata
            )

        if 'content-length' in metadata.headers:
            obj_size = int(metadata.headers['content-length'])

        obj_chunk_size, obj_chunk_number = chunk_size, chunk_number
        if obj_size is None:
            # Size unknown, so the object is a single partition of unset size
            obj_size = 1

        if 'bytes' not in metadata.headers.get('accept-ranges', '').lower():
            # Without range requests, every partition would read the whole object
            obj_chunk_size = obj_chunk_number = None

        return _build_partitions(
            entry,
            lambda: CloudObjectUrl(object_url),
            obj_size,
            obj_chunk_size,
            obj_chunk_number,
            obj_newline,
            f'url {object_url}'
        )

    return _collect_partitions(_split, map_func_args_list)


def _expand_paths(map_func_args_list: List[Entry]) -> List[Entry]:
    """
    Replaces every directory entry with one entry per file it contains,
    dropping duplicates and anything that is not a file. A path that does
    not exist raises FileNotFoundError
    """
    files = set()
    expanded = []

    for elem in map_func_args_list:
        if not os.path.exists(elem['obj']):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), elem['obj'])
        if os.path.isdir(elem['obj']):
            path = elem['obj']
            for filename in os.listdir(path):
                full_path = os.path.join(path, filename)
                if full_path in files or not os.path.isfile(full_path):
                    continue
                files.add(full_path)
                new_elem = elem.copy()
                new_elem['obj'] = full_path
                expanded.append(new_elem)
        elif os.path.isfile(elem['obj']):
            if elem['obj'] in files:
                continue
            files.add(elem['obj'])
            expanded.append(elem)

    return expanded


def _split_objects_from_paths(
    map_func_args_list: List[Entry],
    chunk_size: Optional[int],
    chunk_number: Optional[int],
    obj_newline: Optional[str]
) -> Tuple[List[Entry], List[int]]:
    """
    Creates partitions from a list of local files and directories
    """
    _log_chunk_settings(chunk_size, chunk_number)

    def _split(entry):
        path = entry['obj']
        obj_size = int(os.stat(path).st_size)
        return _build_partitions(
            entry,
            lambda: CloudObjectLocal(path),
            obj_size,
            chunk_size,
            chunk_number,
            obj_newline,
            f'path {path}'
        )

    files = _expand_paths(map_func_args_list)
    if not files:
        raise Exception('No objects found')

    return _collect_partitions(_split, files)


def _glob_list_prefix(pattern: str) -> str:
    """
    Returns the part of a glob pattern before its first special character,
    the longest prefix every key it matches starts with
    """
    special = [pattern.index(c) for c in '*?\\' if c in pattern]
    return pattern[:min(special)]


def _resolve_object_storage(
    map_func_args_list: List[Entry],
    internal_storage: Any,
    config: Dict[str, Any]
) -> Any:
    """
    Rewrites every entry as a full storage URL, and returns the client they
    all point to. Only one storage backend is supported per map call
    """
    backends = set()

    for elem in map_func_args_list:
        if isinstance(elem['obj'], CloudObject):
            elem['obj'] = (
                f"{elem['obj'].backend}://{elem['obj'].bucket}/{elem['obj'].key}"
            )
        sb, _, _, _ = utils.split_object_url(elem['obj'])
        if sb is None:
            sb = internal_storage.backend
            elem['obj'] = f"{sb}://{elem['obj']}"
        backends.add(sb)

    if len(backends) > 1:
        raise Exception(
            'Process objects from multiple storage backends is not supported. '
            f'Current storage backends: {backends}'
        )

    sb = backends.pop()
    if sb == internal_storage.backend:
        return internal_storage.storage
    return Storage(config=config, backend=sb)


def _list_objects(
    storage: Any,
    sb: str,
    bucket: str,
    prefix: str,
    obj_name: str
) -> List[Dict[str, Any]]:
    """
    Lists the metadata of the objects one entry refers to, be it a single
    key, a glob pattern, a prefix or a whole bucket
    """
    if obj_name:
        if '*' in prefix or '*' in obj_name:
            match_pattern = posixpath.join(prefix, obj_name)
            prefix = _glob_list_prefix(match_pattern)
            logger.debug(
                f"Listing objects with Globber {match_pattern} "
                f"in {sb}://{'/'.join([bucket, prefix])}"
            )
            return storage.list_objects(bucket, prefix, match_pattern)

        prefix = prefix + '/' if prefix else prefix
        logger.debug(
            f"Head on object  {sb}://{'/'.join([bucket, prefix, obj_name])}"
        )
        object_key = posixpath.join(prefix, obj_name)
        head_md = storage.head_object(bucket, object_key)
        content_length = head_md.get('content-length')
        if content_length is None:
            raise KeyError(
                f"The {sb} backend reported no content-length for "
                f"{object_key}, so its size is unknown"
            )
        head_md['Key'] = object_key
        head_md['Size'] = int(content_length)
        return [head_md]

    if prefix:
        if '*' in prefix:
            # a folder: every object, at any depth, inside the folders the
            # pattern matches, but not an object named like one of them
            match_pattern = prefix + '/*/**'
            prefix = _glob_list_prefix(match_pattern)
            logger.debug(
                f"Listing prefixes with Globber {match_pattern} "
                f"in {sb}://{'/'.join([bucket, prefix])}"
            )
        else:
            match_pattern = None
            prefix = prefix + '/'
            logger.debug(
                f"Listing prefixes in {sb}://{'/'.join([bucket, prefix])}"
            )

        return storage.list_objects(bucket, prefix, match_pattern)

    logger.debug(f"Listing objects in {sb}://{bucket}")
    return storage.list_objects(bucket)


def _split_objects_from_object_storage(
    map_func_args_list: List[Entry],
    chunk_size: Optional[int],
    chunk_number: Optional[int],
    internal_storage: Any,
    config: Dict[str, Any],
    obj_newline: Optional[str]
) -> Tuple[List[Entry], List[int]]:
    """
    Creates partitions from a list of buckets, prefixes or object keys
    """
    _log_chunk_settings(chunk_size, chunk_number)
    storage = _resolve_object_storage(
        map_func_args_list, internal_storage, config
    )

    partitions = []
    parts_per_object = []
    total_objects = 0

    for elem in map_func_args_list:
        params = {k: v for k, v in elem.items() if k != 'obj'}
        sb, bucket, prefix, obj_name = utils.split_object_url(elem['obj'])
        objects = _list_objects(storage, sb, bucket, prefix, obj_name)

        for dobj in objects:
            key = dobj['Key']
            if key.endswith('/'):
                logger.debug(
                    f'Discarding object "{key}" as it is a prefix folder (0.0B)'
                )
                continue

            total_objects += 1
            obj_partitions, nparts = _build_partitions(
                {'obj': f'{sb}://{bucket}/{key}', **params},
                lambda: CloudObject(sb, bucket, key),
                dobj['Size'],
                chunk_size,
                chunk_number,
                obj_newline,
                f'object {key}'
            )
            partitions.extend(obj_partitions)
            parts_per_object.append(nparts)

    logger.debug(f"Total objects found: {total_objects}")
    if total_objects == 0:
        raise Exception('No objects found')

    return partitions, parts_per_object
