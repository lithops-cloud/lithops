import os
import sys
import json
import logging
import uuid
import urllib3
from . import config as betabs_config
from kubernetes import client, config
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import is_pywren_function
from pywren_ibm_cloud.compute.utils import create_function_handler_zip
from pywren_ibm_cloud.storage.utils import create_runtime_meta_key
from pywren_ibm_cloud.config import JOBS_PREFIX
from pywren_ibm_cloud.storage import InternalStorage

urllib3.disable_warnings()
logging.getLogger('kubernetes').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)
logging.getLogger('requests_oauthlib').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class BetaBSBackend:
    """
    A wrap-up around Beta BS backend.
    """

    def __init__(self, beta_bs_config, storage_config):
        logger.debug("Creating Beta BS client")
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.name = 'betabs'
        self.beta_bs_config = beta_bs_config
        self.is_pywren_function = is_pywren_function()
        self.storage_config = storage_config
        self.internal_storage = InternalStorage(storage_config)
        
        config.load_kube_config(config_file = beta_bs_config.get('kubectl_config'))
        self.capi = client.CustomObjectsApi()

        self.user_agent = beta_bs_config['user_agent']
        contexts = config.list_kube_config_contexts(config_file = beta_bs_config.get('kubectl_config'))
        
        current_context = contexts[1].get('context')
        self.user = current_context.get('user')
        
        self.user_key = self.user
        self.package = 'pywren_v{}_{}'.format(__version__, self.user_key)
        self.namespace = current_context.get('namespace', 'default')
        self.cluster = current_context.get('cluster')

        log_msg = ('PyWren v{} init for Beta BS - Namespace: {} - '
                   'Cluster: {} - User {}'.format(__version__, self.namespace, self.cluster, self.user))
        if not self.log_level:
            print(log_msg)
        logger.info("Beta BS client created successfully")

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

  
    def _unformat_action_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return betabs_config.RUNTIME_DEFAULT[python_version]

    def _delete_function_handler_zip(self):
        os.remove(betabs_config.FH_ZIP_LOCATION)
    
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

        create_function_handler_zip(betabs_config.FH_ZIP_LOCATION, 'pywrenentry.py', __file__)

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        if not self.log_level:
            cmd = cmd + " >/dev/null 2>&1"

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = 'docker push {}'.format(docker_image_name)
        if not self.log_level:
            cmd = cmd + " >/dev/null 2>&1"
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Creates a new runtime from an already built Docker image
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        runtime_meta = self._generate_runtime_meta(docker_image_name)

        logger.info('Creating new PyWren runtime based on Docker image {}'.format(docker_image_name))
        return runtime_meta

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        pass;

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

    def invoke(self, docker_image_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        
        activation_id = str(uuid.uuid4()).replace('-', '')[:12]
        payload['activation_id'] = activation_id + payload['call_id']

        job_desc = betabs_config.JOB_RUN_RESOURCE
        job_desc['apiVersion'] = self.beta_bs_config['api_version']
        job_desc['spec']['jobDefinitionSpec']['containers'][0]['image'] = docker_image_name
        job_desc['spec']['jobDefinitionSpec']['containers'][0]['env'][0]['value'] = 'payload'
        job_desc['spec']['jobDefinitionSpec']['containers'][0]['env'][1]['value'] = self._dict_to_binary(payload)
        job_desc['spec']['jobDefinitionSpec']['containers'][0]['resources']['requests']['memory'] = str(runtime_memory) +'Mi'
        job_desc['spec']['jobDefinitionSpec']['containers'][0]['resources']['requests']['cpu'] = self.beta_bs_config['runtime_cpu']
        job_desc['metadata']['name'] = payload['activation_id']

        logger.info("About to invoke beta job for activation id {}".format(job_desc['metadata']['name']))
        res = self.capi.create_namespaced_custom_object(
            group=self.beta_bs_config['group'],
            version=self.beta_bs_config['version'],
            namespace=self.namespace,
            plural="jobruns",
            body=job_desc,
        )
        if (logging.getLogger().level == logging.DEBUG):
            debug_res = dict(res)
            debug_res['spec']['jobDefinitionSpec']['containers'][0]['env'][1]['value'] = ''
            logger.debug(debug_res)
            del debug_res

        return res['metadata']['name']

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.cluster, self.namespace, service_name)

        return runtime_key

    def cleanup(self, activation_id):
        logger.debug("Cleanup for activation_id {}".format(activation_id))
        res = self.capi.delete_namespaced_custom_object(
            group=self.beta_bs_config['group'],
            version=self.beta_bs_config['version'],
            name=activation_id,
            namespace=self.namespace,
            plural="jobruns",
            body=client.V1DeleteOptions(),
        )

    
    def _format_service_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _generate_runtime_meta(self, docker_image_name):
        try:
            activation_id = str(uuid.uuid4()).replace('-', '')[:12]
            self.storage_config['activation_id'] = 'pywren-' + activation_id
            job_desc = betabs_config.JOB_RUN_RESOURCE
            job_desc['apiVersion'] = self.beta_bs_config['api_version']
            job_desc['spec']['jobDefinitionSpec']['containers'][0]['image'] = docker_image_name
            job_desc['spec']['jobDefinitionSpec']['containers'][0]['env'][0]['value'] = 'preinstals'
            job_desc['spec']['jobDefinitionSpec']['containers'][0]['env'][1]['value'] = self._dict_to_binary(self.storage_config)
            job_desc['metadata']['name'] ='pywren-' + activation_id
    
            logger.info("About to invoke beta_bs job to get runtime metadata")
            logger.info(job_desc)
            res = self.capi.create_namespaced_custom_object(
                group=self.beta_bs_config['group'],
                version=self.beta_bs_config['version'],
                namespace=self.namespace,
                plural="jobruns",
                body=job_desc,
            )
            logger.debug(res)
    
            # we need to read runtime metadata from COS in retry
            import time
            time.sleep(10)
            status_key = create_runtime_meta_key(JOBS_PREFIX, self.storage_config['activation_id'])
            json_str = self.internal_storage.get_cobject(key = status_key)
            runtime_meta = json.loads(json_str.decode("ascii"))

        except Exception:
            raise("Unable to invoke 'modules' action")

        #runtime_meta = {'preinstalls': [['OpenSSL', True], ['PIL', True], ['__future__', False], ['_asyncio', False], ['_bisect', False], ['_blake2', False], ['_bootlocale', False], ['_bz2', False], ['_cffi_backend', False], ['_codecs_cn', False], ['_codecs_hk', False], ['_codecs_iso2022', False], ['_codecs_jp', False], ['_codecs_kr', False], ['_codecs_tw', False], ['_collections_abc', False], ['_compat_pickle', False], ['_compression', False], ['_contextvars', False], ['_crypt', False], ['_csv', False], ['_ctypes', False], ['_ctypes_test', False], ['_curses', False], ['_curses_panel', False], ['_datetime', False], ['_dbm', False], ['_decimal', False], ['_dummy_thread', False], ['_elementtree', False], ['_gdbm', False], ['_hashlib', False], ['_heapq', False], ['_json', False], ['_lsprof', False], ['_lzma', False], ['_markupbase', False], ['_md5', False], ['_multibytecodec', False], ['_multiprocessing', False], ['_opcode', False], ['_osx_support', False], ['_pickle', False], ['_posixsubprocess', False], ['_py_abc', False], ['_pydecimal', False], ['_pyio', False], ['_queue', False], ['_random', False], ['_sha1', False], ['_sha256', False], ['_sha3', False], ['_sha512', False], ['_sitebuiltins', False], ['_socket', False], ['_sqlite3', False], ['_ssl', False], ['_strptime', False], ['_struct', False], ['_sysconfigdata_m_linux_x86_64-linux-gnu', False], ['_testbuffer', False], ['_testcapi', False], ['_testimportmultiple', False], ['_testmultiphase', False], ['_threading_local', False], ['_tkinter', False], ['_uuid', False], ['_weakrefset', False], ['_xxtestfuzz', False], ['abc', False], ['aifc', False], ['antigravity', False], ['argparse', False], ['array', False], ['ast', False], ['asynchat', False], ['asyncio', True], ['asyncore', False], ['attr', True], ['audioop', False], ['autobahn', True], ['automat', True], ['base64', False], ['bdb', False], ['binascii', False], ['binhex', False], ['bisect', False], ['botocore', True], ['bs4', True], ['bson', True], ['bz2', False], ['cProfile', False], ['calendar', False], ['cassandra', True], ['certifi', True], ['certs', True], ['cffi', True], ['cgi', False], ['cgitb', False], ['chardet', True], ['chunk', False], ['click', True], ['clidriver', True], ['cloudant', True], ['cmath', False], ['cmd', False], ['code', False], ['codecs', False], ['codeop', False], ['collections', True], ['colorsys', False], ['compileall', False], ['concurrent', True], ['configparser', False], ['constantly', True], ['contextlib', False], ['contextvars', False], ['copy', False], ['copyreg', False], ['crypt', False], ['cryptography', True], ['cssselect', True], ['csv', False], ['ctypes', True], ['curses', True], ['dataclasses', False], ['datetime', False], ['dateutil', True], ['dbm', True], ['decimal', False], ['difflib', False], ['dis', False], ['distutils', True], ['doctest', False], ['docutils', True], ['dummy_threading', False], ['easy_install', False], ['elasticsearch', True], ['elasticsearch5', True], ['email', True], ['encodings', True], ['ensurepip', True], ['enum', False], ['etcd3', True], ['exampleproj', True], ['exec__', False], ['fcntl', False], ['filecmp', False], ['fileinput', False], ['flask', True], ['fnmatch', False], ['formatter', False], ['fractions', False], ['ftplib', False], ['functools', False], ['genericpath', False], ['getopt', False], ['getpass', False], ['gettext', False], ['gevent', True], ['glob', False], ['greenlet', False], ['gridfs', True], ['grp', False], ['grpc', True], ['gzip', False], ['hamcrest', True], ['hashlib', False], ['heapq', False], ['hmac', False], ['html', True], ['http', True], ['httplib2', True], ['hyperlink', True], ['ibm_boto3', True], ['ibm_botocore', True], ['ibm_db', False], ['ibm_db_dbi', False], ['ibm_s3transfer', True], ['ibmcloudsql', True], ['idlelib', True], ['idna', True], ['imaplib', False], ['imghdr', False], ['imp', False], ['importlib', True], ['incremental', True], ['inspect', False], ['io', False], ['ipaddress', False], ['itsdangerous', True], ['jinja2', True], ['jmespath', True], ['json', True], ['jwt', True], ['kafka', True], ['keyword', False], ['lib2to3', True], ['linecache', False], ['locale', False], ['logging', True], ['lxml', True], ['lzma', False], ['macpath', False], ['mailbox', False], ['mailcap', False], ['main__', False], ['markupsafe', True], ['math', False], ['mimetypes', False], ['mmap', False], ['modulefinder', False], ['multiprocessing', True], ['netrc', False], ['nis', False], ['nntplib', False], ['ntpath', False], ['nturl2path', False], ['numbers', False], ['numpy', True], ['opcode', False], ['operator', False], ['optparse', False], ['os', False], ['ossaudiodev', False], ['pandas', True], ['parsel', True], ['parser', False], ['pathlib', False], ['pdb', False], ['pickle', False], ['pickletools', False], ['pika', True], ['pip', True], ['pipes', False], ['pkg_resources', True], ['pkgutil', False], ['platform', False], ['plistlib', False], ['poplib', False], ['posixpath', False], ['pprint', False], ['profile', False], ['pstats', False], ['psycopg2', True], ['pty', False], ['py_compile', False], ['pyarrow', True], ['pyasn1', True], ['pyasn1_modules', True], ['pyclbr', False], ['pycparser', True], ['pydispatch', True], ['pydoc', False], ['pydoc_data', True], ['pyexpat', False], ['pymongo', True], ['pytz', True], ['queue', False], ['queuelib', True], ['quopri', False], ['random', False], ['re', False], ['readline', False], ['redis', True], ['reprlib', False], ['requests', True], ['resource', False], ['rlcompleter', False], ['runpy', False], ['sched', False], ['scipy', True], ['scrapy', True], ['secrets', False], ['select', False], ['selectors', False], ['service_identity', True], ['setuptools', True], ['shelve', False], ['shlex', False], ['shutil', False], ['signal', False], ['simplejson', True], ['site', False], ['six', False], ['sklearn', True], ['smtpd', False], ['smtplib', False], ['sndhdr', False], ['socket', False], ['socketserver', False], ['soupsieve', True], ['spwd', False], ['sqlite3', True], ['sre_compile', False], ['sre_constants', False], ['sre_parse', False], ['ssl', False], ['stat', False], ['statistics', False], ['string', False], ['stringprep', False], ['struct', False], ['subprocess', False], ['sunau', False], ['symbol', False], ['symtable', False], ['sysconfig', False], ['syslog', False], ['tabnanny', False], ['tarfile', False], ['telnetlib', False], ['tempfile', False], ['tenacity', True], ['termios', False], ['testfunctions', False], ['tests', True], ['textwrap', False], ['this', False], ['threading', False], ['timeit', False], ['tkinter', True], ['token', False], ['tokenize', False], ['tornado', True], ['trace', False], ['traceback', False], ['tracemalloc', False], ['tty', False], ['turtle', False], ['turtledemo', True], ['twisted', True], ['txaio', True], ['types', False], ['typing', False], ['unicodedata', False], ['unittest', True], ['urllib', True], ['urllib3', True], ['uu', False], ['uuid', False], ['venv', True], ['virtualenv', False], ['virtualenv_support', True], ['w3lib', True], ['warnings', False], ['watson_developer_cloud', True], ['wave', False], ['weakref', False], ['webbrowser', False], ['werkzeug', True], ['wheel', True], ['wsgiref', True], ['xdrlib', False], ['xml', True], ['xmlrpc', True], ['xxlimited', False], ['zipapp', False], ['zipfile', False], ['zlib', False]], 'python_ver': '3.7'}

        return runtime_meta
