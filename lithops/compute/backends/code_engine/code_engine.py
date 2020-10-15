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

import os
import sys
import logging
import uuid
import urllib3
import copy
import json
from . import config as codeengine_config
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from lithops.utils import version_str
from lithops.version import __version__
from lithops.utils import is_lithops_function
from lithops.compute.utils import create_function_handler_zip
from lithops.storage.utils import create_runtime_meta_key
from lithops.config import JOBS_PREFIX
from lithops.storage import InternalStorage
from lithops.storage.utils import StorageNoSuchKeyError

urllib3.disable_warnings()
logging.getLogger('kubernetes').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)
logging.getLogger('requests_oauthlib').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class CodeEngineBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, code_engine_config, storage_config):
        logger.debug("Creating Code Engine client")
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'code_engine'
        self.code_engine_config = code_engine_config
        self.is_lithops_function = is_lithops_function()
        self.storage_config = storage_config
        self.internal_storage = InternalStorage(storage_config)

        config.load_kube_config(config_file = code_engine_config.get('kubectl_config'))
        self.capi = client.CustomObjectsApi()

        self.user_agent = code_engine_config['user_agent']
        contexts = config.list_kube_config_contexts(config_file = code_engine_config.get('kubectl_config'))

        current_context = contexts[1].get('context')
        self.user = current_context.get('user')

        self.user_key = self.user
        self.package = 'lithops_v{}_{}'.format(__version__, self.user_key)
        self.namespace = current_context.get('namespace', 'default')
        self.cluster = current_context.get('cluster')

        log_msg = ('Lithops v{} init for Code Engine - Namespace: {} - '
                   'Cluster: {} - User {}'.format(__version__, self.namespace, self.cluster, self.user))
        if not self.log_active:
            print(log_msg)
        self.job_def_ids = set()
        logger.info("Code Engine client created successfully")

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '-').replace(':', '-').replace('.','-')
        return '{}-{}mb'.format(runtime_name, runtime_memory)

  
    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return codeengine_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        logger.debug("About to delete {}".format(codeengine_config.FH_ZIP_LOCATION))
        res = os.remove(codeengine_config.FH_ZIP_LOCATION)
        logger.debug(res)
    
    def _dict_to_binary(self, the_dict):
        str = json.dumps(the_dict)
        binary = ' '.join(format(ord(letter), 'b') for letter in str)
        return binary
    

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        create_function_handler_zip(codeengine_config.FH_ZIP_LOCATION, 'lithopsentry.py', __file__)

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        print(cmd)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = 'docker push {}'.format(docker_image_name)
        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime from an already built Docker image
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        logger.info('Creating new Lithops runtime based on Docker image {}'.format(docker_image_name))
        
        action_name = self._format_action_name(docker_image_name, memory)
        if self.is_job_def_exists(action_name) == False:
            logger.debug("No job definition {} exists".format(action_name))
            action_name = self._create_job_definition(docker_image_name, memory, action_name)

        runtime_meta = self._generate_runtime_meta(action_name)
        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        We need to delete job definition
        """
        def_id = self._format_action_name(docker_image_name, memory)
        self._job_def_cleanup(def_id)

    def delete_all_runtimes(self):
        """
        Deletes all runtimes from all packages
        """
        pass;

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        return []

    def invoke(self, docker_image_name, runtime_memory, payload_cp):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        payload = copy.deepcopy(payload_cp)
        if payload['remote_invoker'] == False:
            raise ("Code Engine Array jobs - only remote_invoker = True is allowed")
        array_size = len(payload['job_description']['data_ranges'])
        runtime_memory_array = payload['job_description']['runtime_memory']
        def_id = self._format_action_name(docker_image_name, runtime_memory_array)
        logger.debug("Job definition id {}".format(def_id))
        if self.is_job_def_exists(def_id) == False:
            def_id = self._create_job_definition(docker_image_name, runtime_memory_array, def_id)

        self.job_def_ids.add(def_id)
        current_location = os.path.dirname(os.path.abspath(__file__))
        job_run_file = os.path.join(current_location, 'job_run.json')
        logger.debug("Going to open {} ".format(job_run_file))
        with open(job_run_file) as json_file:
            job_desc = json.load(json_file)

            activation_id = str(uuid.uuid4()).replace('-', '')[:12]
            payload['activation_id'] = activation_id
            payload['call_id'] = activation_id

            job_desc['metadata']['name'] = payload['activation_id']
            job_desc['metadata']['namespace'] = self.namespace
            job_desc['apiVersion'] = self.code_engine_config['api_version']
            job_desc['spec']['jobDefinitionRef'] = str(def_id)
            job_desc['spec']['jobDefinitionSpec']['arraySpec'] = '0-' + str(array_size - 1)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['name'] = str(def_id)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][0]['value'] = 'payload'
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = self._dict_to_binary(payload)
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['resources']['requests']['memory'] = str(runtime_memory_array) +'Mi'
            job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])

            logger.info("Before invoke job name {}".format(job_desc['metadata']['name']))
            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(job_desc)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("request - {}".format(debug_res))
                del debug_res
            try:
                res = self.capi.create_namespaced_custom_object(
                    group=self.code_engine_config['group'],
                    version=self.code_engine_config['version'],
                    namespace=self.namespace,
                    plural="jobruns",
                    body=job_desc,
                )
            except Exception as e:
                print(e)
            logger.info("After invoke job name {}".format(job_desc['metadata']['name']))
    
            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res
    
            return res['metadata']['name']

    def _create_job_definition(self, docker_image_name, runtime_memory, activation_id):
        """
        Invoke -- return information about this invocation
        """
        current_location = os.path.dirname(os.path.abspath(__file__))
        job_def_file = os.path.join(current_location, 'job_def.json')

        with open(job_def_file) as json_file:
            job_desc = json.load(json_file)

            job_desc['apiVersion'] = self.code_engine_config['api_version']
            job_desc['spec']['template']['containers'][0]['image'] = docker_image_name
            job_desc['spec']['template']['containers'][0]['name'] = activation_id
            job_desc['spec']['template']['containers'][0]['env'][0]['value'] = 'payload'
            if runtime_memory is not None:
                job_desc['spec']['template']['containers'][0]['resources']['requests']['memory'] = str(runtime_memory) +'Mi'
            job_desc['spec']['template']['containers'][0]['resources']['requests']['cpu'] = str(self.code_engine_config['runtime_cpu'])
            job_desc['metadata']['name'] = activation_id

            logger.info("Before invoke job name {}".format(job_desc['metadata']['name']))
            try:
                res = self.capi.create_namespaced_custom_object(
                    group=self.code_engine_config['group'],
                    version=self.code_engine_config['version'],
                    namespace=self.namespace,
                    plural="jobdefinitions",
                    body=job_desc,
                )
            except Exception as e:
                print(e)
            logger.info("After invoke job name {}".format(job_desc['metadata']['name']))

            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res
    
            return res['metadata']['name']

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(docker_image_name)
        runtime_key = os.path.join(self.namespace, service_name)

        return runtime_key

    def _job_run_cleanup(self, activation_id):
        logger.debug("Cleanup for activation_id {}".format(activation_id))
        try:
            res = self.capi.delete_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                name=activation_id,
                namespace=self.namespace,
                plural="jobruns",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Cleanup - job name {} was not found (404)".format(activation_id))

    def _job_def_cleanup(self, jobdef_id):
        logger.debug("Cleanup for job_definition {}".format(jobdef_id))
        try:
            res = self.capi.delete_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                name=jobdef_id,
                namespace=self.namespace,
                plural="jobdefinitions",
                body=client.V1DeleteOptions(),
            )
        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Cleanup - job definition {} was not found (404)".format(self.jobdef_id))

    def is_job_def_exists(self, job_def_name):
        logger.debug("Check if job_definition {} exists".format(job_def_name))
        try:
            res = self.capi.get_namespaced_custom_object(group=self.code_engine_config['group'],
                                                         version=self.code_engine_config['version'],
                                                         namespace=self.namespace,
                                                         plural="jobdefinitions",
                                                         name=job_def_name)

        except ApiException as e:
            # swallow error
            if (e.status == 404):
                logger.info("Job definition {} was not found (404)".format(job_def_name))
                return False
        logger.info("Job definition {} was found".format(job_def_name))
        return True

    def _format_service_name(self, runtime_name, runtime_memory = None):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        if (runtime_memory is not None):
            return '{}--{}mb'.format(runtime_name, runtime_memory)
        return runtime_name

    def _generate_runtime_meta(self, job_def_name):
        try:
            current_location = os.path.dirname(os.path.abspath(__file__))
            job_run_file = os.path.join(current_location, 'job_run.json')

            with open(job_run_file) as json_file:
                job_desc = json.load(json_file)

                activation_id = 'lithops-' + str(uuid.uuid4()).replace('-', '')[:12]
                self.storage_config['activation_id'] = activation_id

                job_desc['metadata']['name'] = activation_id
                job_desc['metadata']['namespace'] = self.namespace
                job_desc['apiVersion'] = self.code_engine_config['api_version']
                job_desc['spec']['jobDefinitionRef'] = str(job_def_name)
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['name'] = str(job_def_name)
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][0]['value'] = 'preinstals'
                job_desc['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = self._dict_to_binary(self.storage_config)

            logger.info("About to invoke code engine job to get runtime metadata")
            logger.info(job_desc)
            res = self.capi.create_namespaced_custom_object(
                group=self.code_engine_config['group'],
                version=self.code_engine_config['version'],
                namespace=self.namespace,
                plural="jobruns",
                body=job_desc,
            )
            if (logging.getLogger().level == logging.DEBUG):
                debug_res = copy.deepcopy(res)
                debug_res['spec']['jobDefinitionSpec']['template']['containers'][0]['env'][1]['value'] = ''
                logger.debug("response - {}".format(debug_res))
                del debug_res
    
            # we need to read runtime metadata from COS in retry
            status_key = create_runtime_meta_key(JOBS_PREFIX, self.storage_config['activation_id'])
            import time
            retry = int(1)
            found = False
            while (retry < 5 and not found):
                try:
                    logger.debug("Retry attempt {} to read {}".format(retry, status_key))
                    json_str = self.internal_storage.storage.get_cobject(key = status_key)
                    logger.debug("Found in attempt () to read {}".format(retry, status_key))
                    runtime_meta = json.loads(json_str.decode("ascii"))
                    found = True
                except StorageNoSuchKeyError as e:
                    logger.debug("{} not found in attempt {}. Sleep before retry".format(status_key, retry))
                    retry = retry + 1
                    time.sleep(30)
            if (retry >=5 and not found):
                raise("Unable to invoke 'modules' action")

            json_str = self.internal_storage.storage.get_cobject(key = status_key)
            runtime_meta = json.loads(json_str.decode("ascii"))

        except Exception:
            raise("Unable to invoke 'modules' action")

        #runtime_meta = {'preinstalls': [['OpenSSL', True], ['PIL', True], ['__future__', False], ['_asyncio', False], ['_bisect', False], ['_blake2', False], ['_bootlocale', False], ['_bz2', False], ['_cffi_backend', False], ['_codecs_cn', False], ['_codecs_hk', False], ['_codecs_iso2022', False], ['_codecs_jp', False], ['_codecs_kr', False], ['_codecs_tw', False], ['_collections_abc', False], ['_compat_pickle', False], ['_compression', False], ['_contextvars', False], ['_crypt', False], ['_csv', False], ['_ctypes', False], ['_ctypes_test', False], ['_curses', False], ['_curses_panel', False], ['_datetime', False], ['_dbm', False], ['_decimal', False], ['_dummy_thread', False], ['_elementtree', False], ['_gdbm', False], ['_hashlib', False], ['_heapq', False], ['_json', False], ['_lsprof', False], ['_lzma', False], ['_markupbase', False], ['_md5', False], ['_multibytecodec', False], ['_multiprocessing', False], ['_opcode', False], ['_osx_support', False], ['_pickle', False], ['_posixsubprocess', False], ['_py_abc', False], ['_pydecimal', False], ['_pyio', False], ['_queue', False], ['_random', False], ['_sha1', False], ['_sha256', False], ['_sha3', False], ['_sha512', False], ['_sitebuiltins', False], ['_socket', False], ['_sqlite3', False], ['_ssl', False], ['_strptime', False], ['_struct', False], ['_sysconfigdata_m_linux_x86_64-linux-gnu', False], ['_testbuffer', False], ['_testcapi', False], ['_testimportmultiple', False], ['_testmultiphase', False], ['_threading_local', False], ['_tkinter', False], ['_uuid', False], ['_weakrefset', False], ['_xxtestfuzz', False], ['abc', False], ['aifc', False], ['antigravity', False], ['argparse', False], ['array', False], ['ast', False], ['asynchat', False], ['asyncio', True], ['asyncore', False], ['attr', True], ['audioop', False], ['autobahn', True], ['automat', True], ['base64', False], ['bdb', False], ['binascii', False], ['binhex', False], ['bisect', False], ['botocore', True], ['bs4', True], ['bson', True], ['bz2', False], ['cProfile', False], ['calendar', False], ['cassandra', True], ['certifi', True], ['certs', True], ['cffi', True], ['cgi', False], ['cgitb', False], ['chardet', True], ['chunk', False], ['click', True], ['clidriver', True], ['cloudant', True], ['cmath', False], ['cmd', False], ['code', False], ['codecs', False], ['codeop', False], ['collections', True], ['colorsys', False], ['compileall', False], ['concurrent', True], ['configparser', False], ['constantly', True], ['contextlib', False], ['contextvars', False], ['copy', False], ['copyreg', False], ['crypt', False], ['cryptography', True], ['cssselect', True], ['csv', False], ['ctypes', True], ['curses', True], ['dataclasses', False], ['datetime', False], ['dateutil', True], ['dbm', True], ['decimal', False], ['difflib', False], ['dis', False], ['distutils', True], ['doctest', False], ['docutils', True], ['dummy_threading', False], ['easy_install', False], ['elasticsearch', True], ['elasticsearch5', True], ['email', True], ['encodings', True], ['ensurepip', True], ['enum', False], ['etcd3', True], ['exampleproj', True], ['exec__', False], ['fcntl', False], ['filecmp', False], ['fileinput', False], ['flask', True], ['fnmatch', False], ['formatter', False], ['fractions', False], ['ftplib', False], ['functools', False], ['genericpath', False], ['getopt', False], ['getpass', False], ['gettext', False], ['gevent', True], ['glob', False], ['greenlet', False], ['gridfs', True], ['grp', False], ['grpc', True], ['gzip', False], ['hamcrest', True], ['hashlib', False], ['heapq', False], ['hmac', False], ['html', True], ['http', True], ['httplib2', True], ['hyperlink', True], ['ibm_boto3', True], ['ibm_botocore', True], ['ibm_db', False], ['ibm_db_dbi', False], ['ibm_s3transfer', True], ['ibmcloudsql', True], ['idlelib', True], ['idna', True], ['imaplib', False], ['imghdr', False], ['imp', False], ['importlib', True], ['incremental', True], ['inspect', False], ['io', False], ['ipaddress', False], ['itsdangerous', True], ['jinja2', True], ['jmespath', True], ['json', True], ['jwt', True], ['kafka', True], ['keyword', False], ['lib2to3', True], ['linecache', False], ['locale', False], ['logging', True], ['lxml', True], ['lzma', False], ['macpath', False], ['mailbox', False], ['mailcap', False], ['main__', False], ['markupsafe', True], ['math', False], ['mimetypes', False], ['mmap', False], ['modulefinder', False], ['multiprocessing', True], ['netrc', False], ['nis', False], ['nntplib', False], ['ntpath', False], ['nturl2path', False], ['numbers', False], ['numpy', True], ['opcode', False], ['operator', False], ['optparse', False], ['os', False], ['ossaudiodev', False], ['pandas', True], ['parsel', True], ['parser', False], ['pathlib', False], ['pdb', False], ['pickle', False], ['pickletools', False], ['pika', True], ['pip', True], ['pipes', False], ['pkg_resources', True], ['pkgutil', False], ['platform', False], ['plistlib', False], ['poplib', False], ['posixpath', False], ['pprint', False], ['profile', False], ['pstats', False], ['psycopg2', True], ['pty', False], ['py_compile', False], ['pyarrow', True], ['pyasn1', True], ['pyasn1_modules', True], ['pyclbr', False], ['pycparser', True], ['pydispatch', True], ['pydoc', False], ['pydoc_data', True], ['pyexpat', False], ['pymongo', True], ['pytz', True], ['queue', False], ['queuelib', True], ['quopri', False], ['random', False], ['re', False], ['readline', False], ['redis', True], ['reprlib', False], ['requests', True], ['resource', False], ['rlcompleter', False], ['runpy', False], ['sched', False], ['scipy', True], ['scrapy', True], ['secrets', False], ['select', False], ['selectors', False], ['service_identity', True], ['setuptools', True], ['shelve', False], ['shlex', False], ['shutil', False], ['signal', False], ['simplejson', True], ['site', False], ['six', False], ['sklearn', True], ['smtpd', False], ['smtplib', False], ['sndhdr', False], ['socket', False], ['socketserver', False], ['soupsieve', True], ['spwd', False], ['sqlite3', True], ['sre_compile', False], ['sre_constants', False], ['sre_parse', False], ['ssl', False], ['stat', False], ['statistics', False], ['string', False], ['stringprep', False], ['struct', False], ['subprocess', False], ['sunau', False], ['symbol', False], ['symtable', False], ['sysconfig', False], ['syslog', False], ['tabnanny', False], ['tarfile', False], ['telnetlib', False], ['tempfile', False], ['tenacity', True], ['termios', False], ['testfunctions', False], ['tests', True], ['textwrap', False], ['this', False], ['threading', False], ['timeit', False], ['tkinter', True], ['token', False], ['tokenize', False], ['tornado', True], ['trace', False], ['traceback', False], ['tracemalloc', False], ['tty', False], ['turtle', False], ['turtledemo', True], ['twisted', True], ['txaio', True], ['types', False], ['typing', False], ['unicodedata', False], ['unittest', True], ['urllib', True], ['urllib3', True], ['uu', False], ['uuid', False], ['venv', True], ['virtualenv', False], ['virtualenv_support', True], ['w3lib', True], ['warnings', False], ['watson_developer_cloud', True], ['wave', False], ['weakref', False], ['webbrowser', False], ['werkzeug', True], ['wheel', True], ['wsgiref', True], ['xdrlib', False], ['xml', True], ['xmlrpc', True], ['xxlimited', False], ['zipapp', False], ['zipfile', False], ['zlib', False]], 'python_ver': '3.7'}

        return runtime_meta
