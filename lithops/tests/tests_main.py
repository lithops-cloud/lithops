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
import argparse
import os
from importlib import import_module
import inspect
import pathlib
import sys
import unittest
import logging
import urllib.request
from os import walk

from lithops.storage import Storage
from lithops.config import get_mode, default_config, extract_storage_config, load_yaml_config
from concurrent.futures import ThreadPoolExecutor
from lithops.tests import main_util
from lithops.tests.util_func.storage_util import clean_tests
from lithops.utils import setup_lithops_logger

TEST_MODULES = None
TEST_GROUPS = {}
CONFIG = None
STORAGE_CONFIG = None
STORAGE = None
PREFIX = '__lithops.test'
DATASET_PREFIX = PREFIX + '/dataset'
TEST_FILES_URLS = ["https://www.gutenberg.org/files/60/60-0.txt",
                   "https://www.gutenberg.org/files/215/215-0.txt",
                   "https://www.gutenberg.org/files/1661/1661-0.txt"]
logger = logging.getLogger(__name__)


def get_tests_of_class(class_name):
    """returns a list of all test methods of a given class """
    method_list = []
    for attribute in dir(class_name):
        attribute_value = getattr(class_name, attribute)
        if callable(attribute_value):
            if attribute.startswith('test'):
                method_list.append(attribute)
    return method_list


def print_test_functions():
    """responds to '-t help' from CLI by printing the test functions within the various test_modules"""
    print("\nAvailable test functions:")
    init_test_variables()

    for test_group in sorted(TEST_GROUPS.keys()):
        print(f'\n{test_group}:')
        for test in get_tests_of_class(TEST_GROUPS[test_group]):
            print(f'    ->{test}')


def print_test_groups():
    """responds to '-g help' from CLI by printing test groups within the various test_modules, e.g. storage/map etc. """
    print("\nAvailable test groups:\n")
    init_test_variables()
    for test_group in sorted(TEST_GROUPS.keys()):
        print(f'{test_group} \n-----------------')


def register_test_groups():
    """initializes the TEST_GROUPS variable - test classes within given test modules"""
    global TEST_GROUPS
    for module in TEST_MODULES:
        group_name = str(module).split('test_')[1].split('\'')[0]
        # A test group is created for every module that contains a class inheriting from unittest.TestCase.
        for member in inspect.getmembers(module, inspect.isclass):
            if issubclass(member[1], unittest.TestCase):
                TEST_GROUPS[group_name] = member[1]


def import_test_modules():
    """dynamically imports test modules from test files within the tests package"""
    global TEST_MODULES
    TEST_MODULES = [import_module(module) for module in ["lithops.tests." + file[:-3]
                                                         for file in
                                                         next(walk(pathlib.Path(__file__).parent.absolute()))[2]
                                                         if file.startswith("test_")]]  # and 'template' not in file


def init_test_variables():
    """initializes the global TEST variables in case they haven't been initialized"""
    if not TEST_MODULES:
        import_test_modules()
    if not TEST_GROUPS:
        register_test_groups()


def upload_data_sets():
    """uploads datasets to storage and return a list of the number of words within each test file"""

    def up(param):
        logger.info('Uploading datasets...')
        i, url = param
        content = urllib.request.urlopen(url).read()
        STORAGE.put_object(bucket=STORAGE_CONFIG['bucket'],
                           key='{}/test{}'.format(DATASET_PREFIX, str(i)),
                           body=content)
        return len(content.split())

    with ThreadPoolExecutor() as pool:
        results = list(pool.map(up, enumerate(TEST_FILES_URLS)))
    result_to_compare = sum(results)
    return result_to_compare


def run_tests(test_to_run, config=None, mode=None, group=None, backend=None, storage=None):
    global CONFIG, STORAGE_CONFIG, STORAGE
    test_found = False

    mode = mode or get_mode(backend, config)
    config_ow = {'lithops': {'mode': mode}}
    if storage:
        config_ow['lithops']['storage'] = storage
    if backend:
        config_ow[mode] = {'backend': backend}
    CONFIG = default_config(config, config_ow)
    STORAGE_CONFIG = extract_storage_config(CONFIG)
    STORAGE = Storage(storage_config=STORAGE_CONFIG)
    init_test_variables()

    suite = unittest.TestSuite()

    if group:
        if group not in TEST_GROUPS:
            print('unknown test group, use: "test -g help" to get a list of the available test groups')
            sys.exit()
        suite.addTest(unittest.makeSuite(TEST_GROUPS[group]))

    elif test_to_run == 'all':
        for tester in TEST_GROUPS.values():
            suite.addTest(unittest.makeSuite(tester))

    else:  # user specified a single test
        if test_to_run.find('.') != -1:  # user specified a test class along with the tester, i.e TestClass.tester_name
            classes_to_search = [TEST_GROUPS.get(test_to_run.split('.')[0])]
            test_to_run = test_to_run.split('.')[1]
        else:
            classes_to_search = TEST_GROUPS.values()

        for test_class in classes_to_search:
            if test_to_run in get_tests_of_class(test_class):
                suite.addTest(test_class(test_to_run))
                test_found = True

        if not test_found:
            print('unknown test, use: "test -t help" to get a list of the available testers ')
            sys.exit()

    words_in_data_set = upload_data_sets()
    main_util.init_config(CONFIG, STORAGE, STORAGE_CONFIG, words_in_data_set, TEST_FILES_URLS)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
    clean_tests(STORAGE, STORAGE_CONFIG, PREFIX)  # removes test files previously uploaded to your storage


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="test all Lithops's functionality",
                                     usage='python -m lithops.tests.tests_main [-c CONFIG] [-t TESTNAME] ...')
    parser.add_argument('-c', '--config', metavar='', default=None,
                        help="'path to yaml config file")
    parser.add_argument('-t', '--test', metavar='', default='all',
                        help='run a specific test, type "-t help" for tests list')
    parser.add_argument('-g', '--group', metavar='', default='',
                        help='run all testers belonging to a specific group.'
                             ' type "-g help" for groups list')
    parser.add_argument('-m', '--mode', metavar='', default=None,
                        help='serverless, standalone or localhost')
    parser.add_argument('-b', '--backend', metavar='', default=None,
                        help='compute backend')
    parser.add_argument('-s', '--storage', metavar='', default=None,
                        help='storage backend')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='activate debug logging')
    args = parser.parse_args()

    if args.config:
        if os.path.exists(args.config):
            args.config = load_yaml_config(args.config)
        else:
            raise FileNotFoundError("Provided config file '{}' does not exist".format(args.config))

    log_level = logging.INFO if not args.debug else logging.DEBUG
    setup_lithops_logger(log_level)

    if args.test == 'help':
        print_test_functions()
    else:
        run_tests(args.test, args.config, args.mode, args.backend, args.storage)









# global TEST_CLASSES
#
# for module in TEST_MODULES:
#     for member in inspect.getmembers(module, inspect.isclass):
#         if issubclass(member[1], unittest.TestCase):
#             TEST_CLASSES.append(member[1])


# def register_test_groups():
#     """initializes the TEST_GROUPS variable"""
#     global TEST_GROUPS
#     for module in [str(x) for x in TEST_MODULES]:
#         group_name = module.split('test_')[1].split('\'')[0]

# for test_class in TEST_CLASSES:
#     index = str(test_class).rfind("Test")
#     group_name = str(test_class)[index + 4:-2]
#     TEST_GROUPS[group_name] = test_class


# func_names = []
# for test_class in TEST_GROUPS.values():
#     func_names.extend(get_tests_of_class(test_class))
# for func_name in func_names:
#     print(f'-> {func_name}')
