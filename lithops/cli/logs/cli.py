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
import logging
import click
import os
import time

from lithops.config import LOGS_DIR, FN_LOG_FILE


@click.group()
@click.pass_context
def logs(ctx):
    pass


@logs.command('poll')
def poll():
    logging.basicConfig(level=logging.DEBUG)

    def follow(file):
        line = ''
        while True:
            tmp = file.readline()
            if tmp:
                line += tmp
                if line.endswith("\n"):
                    yield line
                    line = ''
            else:
                time.sleep(1)

    for line in follow(open(FN_LOG_FILE, 'r')):
        print(line, end='')


@logs.command('get')
@click.argument('execution_id')
def get(execution_id):
    log_file = os.path.join(LOGS_DIR, execution_id+'.log')

    if not os.path.isfile(log_file):
        print('The execution id: {} does not exists in logs'.format(execution_id))
        return

    with open(log_file, 'r') as content_file:
        print(content_file.read())
