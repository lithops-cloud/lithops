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
exec(open('lithops/version.py').read())
setup(
    name='lithops',
    version=__version__,
    url='https://github.com/lithops-cloud/lithops',
    author='Gil Vernik',
    description='Run many jobs over IBM Cloud',
    long_description="Lithops lets you transparently run your Python functions in the Cloud",
    author_email='gilv@il.ibm.com',
    packages=find_packages(),
    install_requires=[
        'Click',
        'pandas',
        'PyYAML',
        'python-dateutil',
        'pika==0.13.1',
        'glob2',
        'tqdm',
        'lxml',
        'tblib',
        'docker',
        'requests',
        'seaborn',
        'paramiko',
        'matplotlib',
        'kubernetes',
        'ibm-cos-sdk',
        'redis'
    ],
    extras_require={
        'aws': [
            'boto3'
        ],
        'gcp': [
            'gcsfs',
            'httplib2',
            'google-cloud-storage',
            'google-cloud-pubsub',
            'google-api-python-client',
            'google-auth'
        ],
        'aliyun': [
            'aliyun-fc2',
            'oss2'
        ],
        'azure': [
            'azure-storage-blob==2.1.0',
            'azure-storage-queue==2.1.0'
        ]
    },
    include_package_data=True,
    entry_points='''
        [console_scripts]
        lithops=lithops.cli.cli:cli
    ''',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Natural Language :: English',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    python_requires='>=3.5',
)
