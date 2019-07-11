#!/usr/bin/env python3
from pywren_ibm_cloud.runtime import create_runtime, update_runtime, build_runtime, delete_runtime, clean_runtimes
import logging
import click
import os

logging.basicConfig(level=logging.DEBUG)
os.environ["PYWREN_LOG_LEVEL"] = 'DEBUG'


@click.group()
@click.pass_context
def cli(ctx):
    pass


@cli.command('create')
@click.argument('image_name')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
def create(image_name, memory):
    create_runtime(image_name, memory=memory)


@cli.command('build')
@click.argument('image_name')
def build(image_name):
    build_runtime(image_name)


@cli.command('update')
@click.argument('image_name')
def update(image_name):
    update_runtime(image_name)


@cli.command('delete')
@click.argument('image_name')
def delete(image_name):
    delete_runtime(image_name)


@cli.command('clean')
def clean():
    clean_runtimes()


if __name__ == "__main__":
    cli()
