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
import struct
import io


def uuid_str():
    return str(uuid.uuid4())


def create_executor_id(lenght=13):
    return uuid_str()[0:lenght]


def create_callgroup_id(lenght=8):
    return uuid_str().replace('-', '')[0:lenght]


def timeout_handler(signum, frame):
    raise TimeoutError()


def is_openwhisk():
    """
    Checks if the current execution is in an OpenWhisk function
    """
    if any([k.startswith('__OW_') for k in os.environ.keys()]):
        return True
    return False


class WrappedStreamingBody(object):
    """
    Wrap boto3's StreamingBody object to provide enough Python fileobj functionality
    so that tar/gz can happen in memory

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

    def readline(self):
        # print("Calling readline()")
        try:
            retval = self.sb._raw_stream.readline()
        except struct.error:
            raise EOFError()
        self.pos += len(retval)
        return retval

    def read(self, n=None):
        retval = self.sb.read()
        if retval == "":
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


class WrappedStreamingBodyThreshold(WrappedStreamingBody):
    
    def __init__(self, sb, size, threshold):
        # The StreamingBody we're wrapping
        self.sb = sb
        # Initial position
        self.pos = 0
        # Size of the object
        self.size = size
        # Added data in addition
        self.threshold = threshold

    def read(self, n=None):
        retval = self.sb.read()
        self.pos += len(retval)

        if self.pos > self.size:
            buf = io.BytesIO(retval)
            for line in buf.readlines():
                print(line)
            retval = b''

        return retval


def sdb_to_dict(item):
    attr = item['Attributes']
    return {c['Name'] : c['Value'] for c in attr}


def bytes_to_b64str(byte_data):
    byte_data_64 = base64.b64encode(byte_data)
    byte_data_64_ascii = byte_data_64.decode('ascii')
    return byte_data_64_ascii


def b64str_to_bytes(str_data):
    str_ascii = str_data.encode('ascii')
    byte_data = base64.b64decode(str_ascii)
    return byte_data


def split_s3_url(s3_url):
    if s3_url[:5] != "s3://":
        raise ValueError("URL {} is not valid".format(s3_url))


    splits = s3_url[5:].split("/")
    bucket_name = splits[0]
    key = "/".join(splits[1:])
    return bucket_name, key

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


def verify_args(func, data, object_processing=False):
    # Verify parameters
    none_verify_parameters = ['storage_handler']
    func_sig = inspect.signature(func)
    
    # Check mandatory parameters in function
    if object_processing:
        none_verify_parameters.append('data_stream')
        err_msg = 'parameter in your map_function() is mandatory for pywren.map_reduce(map_function,...)'
        if 'bucket' in func_sig.parameters:
            none_verify_parameters.append('key')
            none_verify_parameters.append('prefix')
            if 'key' not in func_sig.parameters:
                raise ValueError('"key" {}'.format(err_msg))
            if 'data_stream' not in func_sig.parameters:
                raise ValueError('"data_stream" {}'.format(err_msg))
        if 'key' in func_sig.parameters or 'url' in func_sig.parameters:
            if 'data_stream' not in func_sig.parameters:
                raise ValueError('"data_stream" {}'.format(err_msg))
        
    new_parameters = list()
    for param in func_sig.parameters:
        if func_sig.parameters[param].default != None and param not in none_verify_parameters:
            new_parameters.append(func_sig.parameters[param])

    new_func_sig = func_sig.replace(parameters=new_parameters)

    new_data = list()
    for elem in data:
        if type(elem) == dict:
            if set(list(new_func_sig.parameters.keys())) <= set(elem):
                new_data.append(elem)
            else:
                raise ValueError("Check the args names in the data. " \
                                 "You provided these args: {}, and " \
                                 "the args must be: {}".format(list(elem.keys()),
                                                               list(new_func_sig.parameters.keys())))
        elif type(elem) in (list, tuple):
            new_elem = dict(new_func_sig.bind(*list(elem)).arguments)
            new_data.append(new_elem)
        else:
            # single value (string, integer, list, etc)
            new_elem = dict(new_func_sig.bind(elem).arguments)
            new_data.append(new_elem)

    return new_data
