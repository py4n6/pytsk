#!/usr/bin/python
# Script to generate the Python bindings

import os
import sys

import class_parser

def generate_bindings(target, sources, env = None, initialization='',
                      free='talloc_free',
                      current_error_function='aff4_get_current_error'):
    """ Generated the python bindings """
    module_name = os.path.splitext(os.path.basename(target))[0]
    print("Generating automatic python bindings for module %s" % module_name)

    env = env or dict(V = 0)

    ## Sets the free function
    class_parser.FREE = free
    p = class_parser.HeaderParser(module_name, verbose=env['V'])
    p.module.init_string = initialization
    p.parse_filenames(sources)

    fd = open(target, 'w')
    p.write(fd)
    fd.close()

if __name__ == '__main__':

    if len(sys.argv) != 2:
        print "Usage: ./generate_pytsk3.py path_to_source"
        sys.exit(1)

    tsk_source_path = sys.argv[1]
    include_base = "tsk3"

    if not os.path.exists(os.path.join(tsk_source_path, include_base)):
      # sleuthkit 4.1 changed the names of the include headers.
      include_base = "tsk"

    if not os.path.exists(os.path.join(tsk_source_path, include_base)):
        print "Unable to find sleuthkit include headers."
        sys.exit(1)

    sources = [
      os.path.join(tsk_source_path, include_base, "libtsk.h"),
      os.path.join(tsk_source_path, include_base, "base", "tsk_base.h"),
      os.path.join(tsk_source_path, include_base, "fs", "tsk_fs.h"),
      os.path.join(tsk_source_path, include_base, "img", "tsk_img.h"),
      os.path.join(tsk_source_path, include_base, "vs", "tsk_vs.h"),
      "tsk3.h",
    ]

    generate_bindings("pytsk3.c", sources, initialization='tsk_init();')

