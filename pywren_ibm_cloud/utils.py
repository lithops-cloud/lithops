#
# Copyright 2018 PyWren Team
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

import base64
import os
import uuid
import inspect
import subprocess
import struct
import platform
import logging
import io

logger = logging.getLogger(__name__)


def uuid_str():
    return str(uuid.uuid4())


def create_executor_id(lenght=9):
    return uuid_str()[9:9+lenght]


def timeout_handler(signum, frame):
    raise TimeoutError()


def version_str(version_info):
    return "{}.{}".format(version_info[0], version_info[1])


def is_unix_system():
    curret_system = platform.system()
    return curret_system != 'Windows'


def is_remote_cluster():
    """
    Checks if the current execution is remote
    """
    if 'PYWREN_REMOTE' in os.environ:
        return True
    return False


def is_notebook():
    try:
        shell = get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            return True   # Jupyter notebook or qtconsole
        elif shell == 'TerminalInteractiveShell':
            return False  # Terminal running IPython
        else:
            return False  # Other type (?)
    except NameError:
        return False      # Probably standard Python interpreter


def is_object_processing_function(map_function):
    func_sig = inspect.signature(map_function)
    return {'obj', 'url'} & set(func_sig.parameters)


def convert_bools_to_string(extra_env):
    """
    Converts all booleans of a dictionary to a string
    """
    for key in extra_env:
        if type(extra_env[key]) == bool:
            extra_env[key] = str(extra_env[key])

    return extra_env


def sizeof_fmt(num, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def sdb_to_dict(item):
    attr = item['Attributes']
    return {c['Name']: c['Value'] for c in attr}


def bytes_to_b64str(byte_data):
    byte_data_64 = base64.b64encode(byte_data)
    byte_data_64_ascii = byte_data_64.decode('ascii')
    return byte_data_64_ascii


def b64str_to_bytes(str_data):
    str_ascii = str_data.encode('ascii')
    byte_data = base64.b64decode(str_ascii)
    return byte_data


def split_object_url(obj_url):
    if '://' in obj_url:
        sb, path = obj_url.split('://')
    else:
        sb = 'ibm_cos'
        path = obj_url

    sb = 'ibm_cos' if sb == 'cos' else sb

    bucket, full_key = path.split('/', 1) if '/' in path else (path, '')

    if full_key.endswith('/'):
        prefix = full_key
        obj_name = ''
    elif full_key:
        prefix, obj_name = full_key.rsplit('/', 1) if '/' in full_key else ('', full_key)
    else:
        prefix = ''
        obj_name = ''

    return sb, bucket, prefix, obj_name


def split_path(path):

    if (path.startswith("/")):
        path = path[1:]
    ind = path.find("/")
    if (ind > 0):
        bucket_name = path[:ind]
        key = path[ind + 1:]
    else:
        bucket_name = path
        key = None
    return bucket_name, key


def get_current_memory_usage():
    """
    Gets the current memory usage of the runtime.
    To be used only in the action code.
    """
    #cmd = "ps -eo pss | tail -n +2 | awk '{ SUM += $1} END { print SUM/1024}'"
    #memorymbytes = subprocess.check_output(cmd, shell=True).decode("ascii").strip()

    cmd = "python pywren_ibm_cloud/libs/ps_mem/ps_mem.py --total"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    memorybytes = int(process.stdout.read())

    return sizeof_fmt(memorybytes)


def format_data(iterdata, extra_params):
    """
    Converts iteradata to a list with extra_params
    """
    if extra_params and type(extra_params) not in [list, dict]:
        raise Exception('extra_params must be a list or a dict')

    if type(iterdata) in [range, set]:
        data = list(iterdata)
    elif type(iterdata) != list:
        data = [iterdata]
    else:
        data = iterdata

    if extra_params:
        new_iterdata = []
        for data_i in data:
            if type(data_i) in [list, dict] and type(data_i) != type(extra_params):
                raise Exception('Input iterdata and extra_params must be of '
                                'the same type (dict or list)')
            else:
                if type(data_i) == dict:
                    data_i.update(extra_params)
                elif type(data_i) == list:
                    data_i.extend(extra_params)
                elif type(extra_params) == list:
                    new_iterdata.append([data_i, *extra_params])
                else:
                    raise Exception('extra_params cannot be a dict if '
                                    'iteradata is not a dict')

        if new_iterdata:
            data = new_iterdata

    return data


def verify_args(func, iterdata, extra_params):

    data = format_data(iterdata, extra_params)

    # Verify parameters
    non_verify_args = ['ibm_cos', 'swift', 'internal_storage', 'id', 'rabbitmq']
    func_sig = inspect.signature(func)

    new_parameters = list()
    for param in func_sig.parameters:
        if func_sig.parameters[param].default is not None and param not in non_verify_args:
            new_parameters.append(func_sig.parameters[param])

    new_func_sig = func_sig.replace(parameters=new_parameters)

    new_data = list()
    for elem in data:
        if type(elem) == dict:
            if set(list(new_func_sig.parameters.keys())) <= set(elem):
                new_data.append(elem)
            else:
                raise ValueError("Check the args names in the data. "
                                 "You provided these args: {}, and "
                                 "the args must be: {}".format(list(elem.keys()),
                                                               list(new_func_sig.parameters.keys())))
        elif type(elem) in (list, tuple):
            new_elem = dict(new_func_sig.bind(*list(elem)).arguments)
            new_data.append(new_elem)
        else:
            # single value (string, integer, etc)
            new_elem = dict(new_func_sig.bind(elem).arguments)
            new_data.append(new_elem)

    return new_data


class WrappedStreamingBody:
    """
    Wrap boto3's StreamingBody object to provide enough Python fileobj functionality,
    and to discard data added by partitioner and cut lines.

    from https://gist.github.com/debedb/2e5cbeb54e43f031eaf0

    """
    def __init__(self, sb, size):
        # The StreamingBody we're wrapping
        self.sb = sb
        # Initial position
        self.pos = 0
        # Size of the object
        self.size = size

    def tell(self):
        # print("In tell()")
        return self.pos

    def read(self, n=None):
        retval = self.sb.read(n)
        if retval == "":
            raise EOFError()
        self.pos += len(retval)
        return retval

    def readline(self):
        try:
            retval = self.sb.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)
        return retval

    def seek(self, offset, whence=0):
        # print("Calling seek()")
        retval = self.pos
        if whence == 2:
            if offset == 0:
                retval = self.size
            else:
                raise Exception("Unsupported")
        else:
            if whence == 1:
                offset = self.pos + offset
                if offset > self.size:
                    retval = self.size
                else:
                    retval = offset
        # print("In seek(%s, %s): %s, size is %s" % (offset, whence, retval, self.size))

        self.pos = retval
        return retval

    def __str__(self):
        return "WrappedBody"

    def __getattr__(self, attr):
        # print("Calling %s"  % attr)

        if attr == 'tell':
            return self.tell
        elif attr == 'seek':
            return self.seek
        elif attr == 'read':
            return self.read
        elif attr == 'readline':
            return self.readline
        elif attr == '__str__':
            return self.__str__
        else:
            return getattr(self.sb, attr)


class WrappedStreamingBodyPartition(WrappedStreamingBody):

    def __init__(self, sb, size, byterange):
        super().__init__(sb, size)
        # Range of the chunk
        self.range = byterange
        # The first chunk does not contain plusbyte
        self.plusbytes = 0 if not self.range or self.range[0] == 0 else 1
        # To store the first byte of this chunk, which actually is the last byte of previous chunk
        self.first_byte = None
        # Flag that indicates the end of the file
        self.eof = False

    def read(self, n=None):
        if self.eof:
            raise EOFError()
        # Data always contain one byte from the previous chunk,
        # so l'ets check if it is a \n or not
        self.first_byte = self.sb.read(self.plusbytes)
        retval = self.sb.read(n)

        if retval == "":
            raise EOFError()

        self.pos += len(retval)

        first_row_start_pos = 0
        if self.first_byte != b'\n' and self.plusbytes != 0:
            logger.debug('Discarding first partial row')
            # Previous byte is not \n
            # This means that we have to discard first row because it is cut
            first_row_start_pos = retval.find(b'\n')+1

        last_row_end_pos = self.pos
        # Find end of the line in threshold
        if self.pos > self.size:
            buf = io.BytesIO(retval[self.size:])
            buf.readline()
            last_row_end_pos = self.size+buf.tell()
            self.eof = True

        return retval[first_row_start_pos:last_row_end_pos]

    def readline(self):
        if self.eof:
            raise EOFError()

        if not self.first_byte and self.plusbytes != 0:
            self.first_byte = self.sb.read(self.plusbytes)
            if self.first_byte != b'\n':
                logger.debug('Discarding first partial row')
                self.sb._raw_stream.readline()
        try:
            retval = self.sb._raw_stream.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)

        if self.pos >= self.size:
            self.eof = True

        return retval
