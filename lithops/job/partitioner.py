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

CHUNK_THRESHOLD = 128 * 1024  # 128KB

# Backends whose listing supports a glob pattern
_GLOBBER_BACKENDS = ('aws_s3', 'ibm_cos')

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
    urls = []
    paths = []
    objects = []

    logger.debug("Parsing input data")

    for elem in map_iterdata:
        if str(elem['obj']).startswith('http'):
            urls.append(elem)
        elif str(elem['obj']).startswith('/'):
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


def _log_chunk_settings(chunk_size: Optional[int], chunk_number: Optional[int]) -> None:
    if chunk_number:
        logger.debug(f'Chunk number set to {chunk_number}')
    elif chunk_size:
        logger.debug(f'Chunk size set to {chunk_size}')
    else:
        logger.debug('Chunk size and chunk number not set')


def _chunk_from_number(obj_size: int, chunk_number: int) -> int:
    chunk_rest = obj_size % chunk_number
    return (obj_size // chunk_number) + round((chunk_rest / chunk_number) + 0.5)


def _sized_object_chunk(
    obj_size: Optional[int],
    chunk_number: Optional[int],
    chunk_size: Optional[int]
) -> Optional[int]:
    """
    Resolves the chunk size to use for one object. A requested chunk number
    wins over a requested chunk size, and an unset one means a single chunk
    """
    if chunk_number and obj_size:
        return _chunk_from_number(obj_size, chunk_number)
    if chunk_size and obj_size:
        return chunk_size
    if obj_size:
        return obj_size
    return None


def _build_partitions(
    entry: Entry,
    make_obj: Callable[[], Any],
    obj_size: Optional[int],
    obj_chunk_size: Optional[int],
    obj_newline: Optional[str],
    label: str
) -> Partitions:
    """
    Splits one object into as many partitions as its chunk size calls for,
    each one a copy of the entry carrying its own byte range
    """
    if not obj_size or not obj_chunk_size:
        return [], 0

    obj_partitions = []
    size = obj_total_partitions = 0

    parts = obj_size // obj_chunk_size + (obj_size % obj_chunk_size > 0)
    logger.debug(
        f'Creating {parts} partitions from {label} ({sizeof_fmt(obj_size)})'
    )

    while size < obj_size:
        if obj_size <= obj_chunk_size:
            # A single partition reads the whole object, no range needed
            brange = None
            obj_chunk_size = obj_size
        elif obj_newline is None:
            brange = (size, size + obj_chunk_size - 1)
        elif size + obj_chunk_size < obj_size:
            # Records must not be cut in two: a partition starts one byte
            # early to see whether it begins mid record, and overshoots by
            # CHUNK_THRESHOLD so that it can finish the last record it reads
            brange = (
                size - 1 if size > 0 else 0,
                size + obj_chunk_size + CHUNK_THRESHOLD
            )
        else:
            brange = (size - 1, obj_size - 1)
            obj_chunk_size = obj_size - size

        obj_total_partitions += 1

        partition = entry.copy()
        partition['obj'] = make_obj()
        partition['obj'].data_byte_range = brange
        partition['obj'].chunk_size = obj_chunk_size
        partition['obj'].part = obj_total_partitions
        partition['obj'].newline = obj_newline
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
        metadata = requests.head(object_url)

        if 'content-length' in metadata.headers:
            obj_size = int(metadata.headers['content-length'])

        obj_chunk_size = _sized_object_chunk(obj_size, chunk_number, chunk_size)
        if obj_size is None:
            # Size unknown, so the object is a single partition of unset size
            obj_chunk_size = obj_size = 1

        if 'accept-ranges' not in metadata.headers:
            obj_chunk_size = obj_size

        return _build_partitions(
            entry,
            lambda: CloudObjectUrl(object_url),
            obj_size,
            obj_chunk_size,
            obj_newline,
            f'url {object_url}'
        )

    return _collect_partitions(_split, map_func_args_list)


def _expand_paths(map_func_args_list: List[Entry]) -> List[Entry]:
    """
    Replaces every directory entry with one entry per file it contains,
    dropping duplicates and anything that is not a file
    """
    files = set()
    expanded = []

    for elem in map_func_args_list:
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
        obj_chunk_size = _sized_object_chunk(obj_size, chunk_number, chunk_size)
        return _build_partitions(
            entry,
            lambda: CloudObjectLocal(path),
            obj_size,
            obj_chunk_size,
            obj_newline,
            f'path {path}'
        )

    return _collect_partitions(_split, _expand_paths(map_func_args_list))


def _glob_list_prefix(prefix: str, obj_name: str) -> str:
    """Return the listing prefix truncated at the first glob character."""
    if '*' in prefix:
        return prefix[:prefix.index('*')]
    glob_tail = obj_name[:obj_name.index('*')]
    return f'{prefix}/{glob_tail}' if prefix else glob_tail


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
        match_pattern = None
        if sb in _GLOBBER_BACKENDS and ('*' in prefix or '*' in obj_name):
            match_pattern = posixpath.join(prefix, obj_name)
            prefix = _glob_list_prefix(prefix, obj_name)

        prefix = prefix + '/' if prefix else prefix
        if match_pattern is not None:
            logger.debug(
                f"Listing objects with Globber {match_pattern} "
                f"in {sb}://{'/'.join([bucket, prefix])}"
            )
            return storage.list_objects(bucket, prefix, match_pattern)

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
        match_pattern = None
        if sb in _GLOBBER_BACKENDS and '*' in prefix:
            match_pattern = prefix
            prefix = prefix[:prefix.index('*')]
            logger.debug(
                f"Listing prefixes with Globber {match_pattern} "
                f"in {sb}://{'/'.join([bucket, prefix])}"
            )
        else:
            logger.debug(
                f"Listing prefixes in {sb}://{'/'.join([bucket, prefix])}"
            )

        prefix = prefix + '/' if prefix else prefix
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
            obj_size = dobj['Size']
            obj_chunk_size = _sized_object_chunk(
                obj_size, chunk_number, chunk_size
            )
            obj_partitions, nparts = _build_partitions(
                {'obj': f'{sb}://{bucket}/{key}', **params},
                lambda: CloudObject(sb, bucket, key),
                obj_size,
                obj_chunk_size,
                obj_newline,
                f'object {key}'
            )
            partitions.extend(obj_partitions)
            parts_per_object.append(nparts)

    logger.debug(f"Total objects found: {total_objects}")
    if total_objects == 0:
        raise Exception('No objects found')

    return partitions, parts_per_object
