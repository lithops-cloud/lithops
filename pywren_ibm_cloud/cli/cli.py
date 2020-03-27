import os
import click
import logging
from pywren_ibm_cloud.cli.runtime.cli import runtime
from pywren_ibm_cloud.cli import clean_all
from pywren_ibm_cloud.tests import print_help, run_tests


@click.group()
def cli():
    pass


@cli.command('clean')
def clean():
    logging.basicConfig(level=logging.DEBUG)
    os.environ["PYWREN_LOGLEVEL"] = 'DEBUG'
    clean_all()


@cli.command('test')
def test_function():
    import pywren_ibm_cloud as pywren

    def hello(name):
        return 'Hello {}!'.format(name)

    pw = pywren.ibm_cf_executor()
    pw.call_async(hello, 'World')
    result = pw.get_result()[0]
    print()
    if result == 'Hello World!':
        print(result, 'Pywren is working as expected :)')
    else:
        print(result, 'Something went wrong :(')
    print()


@cli.command('verify')
@click.option('--test', default='all', help='run a specific test, type "-t help" for tests list')
@click.option('--config', default=None, help='use json config file')
def test_function(test, config):
    if test == 'help':
        print_help()
    else:
        run_tests(test, config)


cli.add_command(runtime)

if __name__ == '__main__':
    cli()
