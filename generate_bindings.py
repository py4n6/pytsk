#!/usr/bin/python
#
# Script to generate the Python bindings.
#
# Copyright 2012, Joachim Metz <joachim.metz@gmail.com>.
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

import os
import sys

import class_parser


def generate_bindings(target, source_files, env=None, initialization="",
                      free="talloc_free"):
    """ Generated the Python bindings """
    module_name = os.path.splitext(os.path.basename(target))[0]
    print("Generating Python bindings for module %s from %s" % (
        module_name, source_files))

    env = env or dict(V=0)

    # Sets the free function
    class_parser.FREE = free
    p = class_parser.HeaderParser(module_name, verbose=env["V"])
    p.module.init_string = initialization
    p.parse_filenames(source_files)

    fd = open(target, "w")
    p.write(fd)
    fd.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./generate_bindings.py path_to_source")
        sys.exit(1)

    tsk_source_path = sys.argv[1]
    include_base = "tsk3"

    if not os.path.exists(os.path.join(tsk_source_path, include_base)):
        # sleuthkit 4.1 changed the names of the include headers.
        include_base = "tsk"

    if not os.path.exists(os.path.join(tsk_source_path, include_base)):
        print("Unable to find sleuthkit include headers.")
        sys.exit(1)

    sources = [
        os.path.join(tsk_source_path, include_base, "libtsk.h"),
        os.path.join(tsk_source_path, include_base, "base", "tsk_base.h"),
        os.path.join(tsk_source_path, include_base, "fs", "tsk_fs.h"),
        os.path.join(tsk_source_path, include_base, "img", "tsk_img.h"),
        os.path.join(tsk_source_path, include_base, "vs", "tsk_vs.h"),
        "tsk3.h",
    ]

    generate_bindings("pytsk3.c", sources, initialization="tsk_init();")
