#!/usr/bin/env python
from setuptools import setup, find_packages
from itertools import chain


install_requires = [
    'Click',
    'pandas',
    'PyYAML',
    'python-dateutil',
    'pika',
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
    'ibm-vpc',
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
    ],
    'multiprocessing': [
        'pynng'
    ],
    'joblib': [
        'joblib',
        'diskcache',
        'numpy'
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
    description='Lithops lets you transparently run your Python applications in the Cloud',
    author_email='gilv@il.ibm.com, josep.sampe@gmail.com',
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
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Scientific/Engineering',
        'Topic :: System :: Distributed Computing',
    ],
    python_requires='>=3.6',
)
