#!/usr/bin/env python3
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

import sys
from setuptools import setup, find_packages

if sys.version_info < (3,):
    sys.exit('Sorry, Python 2.x is not supported')

if sys.version_info > (3,) and sys.version_info < (3, 4):
    sys.exit('Sorry, Python3 version < 3.4 is not supported')

# http://stackoverflow.com/questions/6344076/differences-between-distribute-distutils-setuptools-and-distutils2

# how to get version info into the project
exec(open('pywren_ibm_cloud/version.py').read())

setup(
    name='pywren_ibm_cloud',
    version=__version__,
    url='https://github.com/pywren/pywren-ibm-cloud',
    author='Gil Vernik',
    description='Run many jobs over IBM Cloud Functions',
    long_description="PyWren lets you transparently run your Python functions"
    "on IBM Cloud Functions",
    author_email='gilv@il.ibm.com',
    packages=find_packages(),
    install_requires=[
        'Click', 'ibm-cos-sdk', 'PyYAML', 'pika==0.13.1',
        'enum34', 'glob2', 'tqdm', 'tblib',
        'requests', 'python-dateutil', 'lxml',
        'pandas', 'seaborn', 'matplotlib'
    ],
    include_package_data=True
)
