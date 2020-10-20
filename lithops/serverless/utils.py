#
# (C) Copyright IBM Corp. 2018
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

import os
import zipfile
import logging
import lithops

logger = logging.getLogger(__name__)


def create_function_handler_zip(dst_zip_location, entry_point_file, entry_point_name=None):

    logger.debug("Creating function handler zip in {}".format(dst_zip_location))

    def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
        for file in os.listdir(full_dir_path):
            full_path = os.path.join(full_dir_path, file)
            if os.path.isfile(full_path):
                zip_file.write(full_path, os.path.join('lithops', sub_dir, file))
            elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

    try:
        with zipfile.ZipFile(dst_zip_location, 'w', zipfile.ZIP_DEFLATED) as lithops_zip:
            module_location = os.path.dirname(os.path.abspath(lithops.__file__))
            entry_point_name = entry_point_name or os.path.basename(entry_point_file)
            lithops_zip.write(entry_point_file, entry_point_name)
            add_folder_to_zip(lithops_zip, module_location)

    except Exception:
        raise Exception('Unable to create the {} package: {}'.format(dst_zip_location))
