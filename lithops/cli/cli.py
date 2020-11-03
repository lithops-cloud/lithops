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

import click
import logging
import lithops
from lithops.cli.runtime.cli import runtime
from lithops.cli import clean_all
from lithops.tests import print_help, run_tests


def set_debug(debug):
    if debug:
        logging.basicConfig(level=logging.DEBUG)


@click.group()
def cli():
    pass


@cli.command('clean')
def clean():
    set_debug(True)
    clean_all()


@cli.command('test')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def test_function(config, debug):
    set_debug(debug)

    def hello(name):
        return 'Hello {}!'.format(name)

    fexec = lithops.FunctionExecutor(config=config)
    fexec.call_async(hello, 'World')
    result = fexec.get_result()
    print()
    if result == 'Hello World!':
        print(result, 'Lithops is working as expected :)')
    else:
        print(result, 'Something went wrong :(')
    print()


@cli.command('verify')
@click.option('--test', '-t', default='all', help='run a specific test, type "-t help" for tests list')
@click.option('--config', '-c', default=None, help='use json config file')
@click.option('--mode', '-m', default=None, help='serverless, standalone or localhost')
@click.option('--debug', '-d', is_flag=True, help='debug mode')
def verify(test, config, mode, debug):
    if test == 'help':
        print_help()
    else:
        set_debug(debug)
        run_tests(test, mode, config)


cli.add_command(runtime)

if __name__ == '__main__':
    cli()
