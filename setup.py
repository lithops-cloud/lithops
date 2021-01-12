#!/usr/bin/env python
from setuptools import setup, find_packages
from itertools import chain


install_requires = [
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
    'redis',
    'joblib',
    'ibm-vpc',
    'namegenerator',
    'cloudpickle',
    'tblib',
    'ps-mem'
]


extras_require = {
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
        'azure-storage-blob',
        'azure-storage-queue'
    ]
}

extras_require["all"] = list(set(chain.from_iterable(extras_require.values())))


# how to get version info into the project
exec(open('lithops/version.py').read())
setup(
    name='lithops',
    version=__version__,
    url='https://github.com/lithops-cloud/lithops',
    author='Gil Vernik, Josep Sampe',
    description='Lithops lets you transparently run your Python functions in the Cloud',
    author_email='gilv@il.ibm.com, josep.sampe@urv.cat',
    packages=find_packages(),
    install_requires=install_requires,
    extras_require=extras_require,
    include_package_data=True,
    entry_points='''
        [console_scripts]
        lithops=lithops.scripts.cli:lithops_cli
    ''',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Natural Language :: English',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Scientific/Engineering',
        'Topic :: System :: Distributed Computing',
    ],
    python_requires='>=3.5',
)
