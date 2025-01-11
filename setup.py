#!/usr/bin/env python
from setuptools import setup, find_packages
from itertools import chain


install_requires = [
    'Click',
    'tabulate',
    'six',
    'PyYAML',
    'pika',
    'tqdm',
    'tblib',
    'requests',
    'paramiko',
    'cloudpickle',
    'tblib',
    'ps-mem',
    'psutil'
]


extras_require = {
    'ibm': [
        'ibm-cos-sdk',
        'ibm-code-engine-sdk',
        'ibm-vpc',
        'kubernetes',
    ],
    'aws': [
        'boto3'
    ],
    'gcp': [
        'httplib2',
        'google-cloud-storage',
        'google-cloud-pubsub',
        'google-api-python-client',
        'google-auth'
    ],
    'azure': [
        'azure-mgmt-resource',
        'azure-mgmt-compute',
        'azure-mgmt-network',
        'azure-identity',
        'azure-storage-blob',
        'azure-storage-queue'
    ],
    'aliyun': [
        'aliyun-fc2',
        'oss2'
    ],
    'ceph': [
        'boto3'
    ],
    'knative': [
        'kubernetes',
    ],
    'kubernetes': [
        'kubernetes',
    ],
    'minio': [
        'boto3'
    ],
    'redis': [
        'redis'
    ],
    'multiprocessing': [
        'redis',
        'pynng'
    ],
    'joblib': [
        'joblib',
        'diskcache',
        'numpy'
    ],
    'plotting': [
        'pandas',
        'matplotlib',
        'seaborn',
        'numpy'
    ],
    'oracle': [
        'oci',
    ],
    'tests': [
        'pytest',
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
    author_email='gilv@ibm.com, josep.sampe@gmail.com',
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
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Scientific/Engineering',
        'Topic :: System :: Distributed Computing',
    ],
    python_requires='>=3.6',
)
