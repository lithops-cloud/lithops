from pywren_ibm_cloud.cli.runtime import create_runtime, update_runtime, build_runtime, delete_runtime
import click
import os


@click.group()
@click.pass_context
def runtime(ctx):
    pass


@runtime.command('create')
@click.argument('image_name')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
def create(image_name, memory):
    create_runtime(image_name, memory=memory)


@runtime.command('build')
@click.argument('image_name')
@click.option('--file', '-f', default=None, help='file needed to build the runtime')
def build(image_name, file):
    build_runtime(image_name, file)


@runtime.command('update')
@click.argument('image_name')
def update(image_name):
    update_runtime(image_name)


@runtime.command('delete')
@click.argument('image_name')
def delete(image_name):
    delete_runtime(image_name)
