#
# Copyright Cloudlab URV 2020
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

from lithops.cli.runtime import create_runtime, update_runtime, build_runtime, delete_runtime
import logging
import click


@click.group()
@click.pass_context
def runtime(ctx):
    pass


@runtime.command('create')
@click.argument('image_name')
@click.option('--memory', default=None, help='memory used by the runtime', type=int)
def create(image_name, memory):
    logging.basicConfig(level=logging.DEBUG)
    create_runtime(image_name, memory=memory)


@runtime.command('build')
@click.argument('image_name')
@click.option('--file', '-f', default=None, help='file needed to build the runtime')
def build(image_name, file):
    logging.basicConfig(level=logging.DEBUG)
    build_runtime(image_name, file)


@runtime.command('update')
@click.argument('image_name')
def update(image_name):
    logging.basicConfig(level=logging.DEBUG)
    update_runtime(image_name)


@runtime.command('delete')
@click.argument('image_name')
def delete(image_name):
    logging.basicConfig(level=logging.DEBUG)
    delete_runtime(image_name)
