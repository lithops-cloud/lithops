#!/usr/bin/env python
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

from setuptools import setup, find_packages

# how to get version info into the project
exec(open('pywren_ibm_cloud/version.py').read())
setup(
    name='pywren_ibm_cloud',
    version=__version__,
    url='https://github.com/pywren/pywren-ibm-cloud',
    author='Gil Vernik',
    description='Run many jobs over IBM Cloud',
    long_description="PyWren lets you transparently run your Python functions on IBM Cloud",
    author_email='gilv@il.ibm.com',
    packages=find_packages(),
    install_requires=[
        'Click', 'ibm-cos-sdk', 'PyYAML', 'pika==0.13.1',
        'enum34', 'glob2', 'tqdm', 'tblib', 'docker',
        'requests', 'python-dateutil', 'lxml',
        'pandas', 'seaborn', 'matplotlib', 'kubernetes'
    ],
    include_package_data=True,
    entry_points='''
        [console_scripts]
        pywren-ibm-cloud=pywren_ibm_cloud.cli.cli:cli
    ''',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.5',
)
