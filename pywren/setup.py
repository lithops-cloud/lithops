#!/usr/bin/env python
import sys

#import pkgconfig
from setuptools import setup, find_packages

if sys.version_info < (2, 7):
    sys.exit('Sorry, Python < 2.7 is not supported')

if sys.version_info > (3,) and sys.version_info < (3, 4):
    sys.exit('Sorry, Python3 version < 3.4 is not supported')

# http://stackoverflow.com/questions/6344076/differences-between-distribute-distutils-setuptools-and-distutils2

# how to get version info into the project
exec(open('pywren_ibm_cloud/version.py').read())

setup(
    name='pywren-ibm-cloud',
    version=__version__,
    url='http://pywren.io',
    author='Eric Jonas',
    description='Run many jobs transparently on IBM Cloud Functions',
    long_description="PyWren lets you transparently run your python functions"
    "on IBM Cloud Functions",
    author_email='jonas@ericjonas.com',
    packages=find_packages(),
    install_requires=[
        'Click', 'ibm-cos-sdk', 'PyYAML',
        'enum34', 'glob2', 'tqdm', 'tblib',
        'requests', 'python-dateutil', 'lxml'
    ],
    tests_requires=[
        'pytest', 'numpy',
    ],
    package_data={
        'pywren': ['jobrunner/jobrunner.py']},
    include_package_data=True
)