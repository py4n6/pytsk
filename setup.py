from distutils.core import setup, Extension
import class_parser
import sys
import os

CONFIG = dict(
    TSK3_HEADER_LOCATION = "/usr/local/include/tsk3/",
    )

def build_python_bindings(target, sources, env = None, initialization='',
                          free='talloc_free',
                          current_error_function='aff4_get_current_error'):
    """ A command to generate python bindings """
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

BOUND_FILES = ("""
    %(TSK3_HEADER_LOCATION)s/libtsk.h
    %(TSK3_HEADER_LOCATION)s/fs/tsk_fs.h
    %(TSK3_HEADER_LOCATION)s/base/tsk_base.h
    %(TSK3_HEADER_LOCATION)s/img/tsk_img.h
    tsk3.h
    """ % CONFIG).split()

if not os.access("pytsk3.c", os.F_OK):
    build_python_bindings("pytsk3.c", BOUND_FILES, initialization='tsk_init();' )

SOURCES = ['tsk3.c', 'class.c', 'pytsk3.c', 'talloc.c', 'error.c']

setup(name='pytsk3',
      version='0.1',
      ext_modules=[Extension('pytsk3', SOURCES,
                             include_dirs=[CONFIG['TSK3_HEADER_LOCATION']],
                             libraries=['tsk3', 'pthread']
                             )
                   ],
      )
