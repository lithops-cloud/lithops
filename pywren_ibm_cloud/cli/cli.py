import os
import click
import logging
from pywren_ibm_cloud.cli.runtime.cli import runtime
from pywren_ibm_cloud.cli import clean_all

logging.basicConfig(level=logging.DEBUG)
os.environ["PYWREN_LOGLEVEL"] = 'DEBUG'


@click.group()
def cli():
    pass


@cli.command('clean')
def clean():
    clean_all()


cli.add_command(runtime)

if __name__ == '__main__':
    cli()
