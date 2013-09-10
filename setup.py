#!/usr/bin/python

import os
import sys

from distutils.core import setup, Extension
from distutils import ccompiler, sysconfig

import class_parser
from generate_bindings import *

import pdb

# Distutils is retarded - We need to monkey patch it to make it saner.
from distutils import cygwinccompiler


# Used by MinGW/Wine cross compilation.
PYTHON_VERSION = "27"
PYTHON_HOME = "%s/.wine/drive_c/Python%s/" % (
    os.environ.get("HOME",""), PYTHON_VERSION)

# Determine the location of the SleuthKit include header files.
CONFIG = dict(
    TSK_HEADERS_LOCATION = "/usr/include/tsk3/",
    LIBRARY_DIRS = [],
    LIBRARIES = ['tsk3'],
    DEFINES = [("HAVE_TSK3_LIBTSK_H", None)])

if not os.path.exists(CONFIG['TSK_HEADERS_LOCATION']):
    CONFIG['TSK_HEADERS_LOCATION'] = "/usr/local/include/tsk3/"

# SleuthKit 4.1 changed the names of the include headers and the library.
if not os.path.exists(CONFIG['TSK_HEADERS_LOCATION']):
    CONFIG['TSK_HEADERS_LOCATION'] = "/usr/include/tsk/"
    CONFIG['LIBRARIES'] = ['tsk']
    CONFIG['DEFINES'] = [("HAVE_TSK_LIBTSK_H", None)]

if not os.path.exists(CONFIG['TSK_HEADERS_LOCATION']):
    CONFIG['TSK_HEADERS_LOCATION'] = "/usr/local/include/tsk/"
    CONFIG['LIBRARIES'] = ['tsk']
    CONFIG['DEFINES'] = [("HAVE_TSK_LIBTSK_H", None)]

if not os.path.exists(CONFIG['TSK_HEADERS_LOCATION']):
    raise EnvironmentError("Unable to find sleuthkit headers in: /usr/include and /usr/local/include.")

CONFIG['HEADERS'] = [CONFIG['TSK_HEADERS_LOCATION']]

# The SleuthKit needs libstdc++, force the include because some builds of
# the SleuthKit forget to explicitly link against it.
CONFIG['LIBRARIES'].append('stdc++')

# This is so horrible but less horrible than interfering with distutils.
try:
    if sys.argv[1] == "mingw-xcompile":
        sys.argv[1] = "build"
        sys.argv.extend(("-c", "mingw32"))
        sysconfig._init_nt()
        CONFIG['HEADERS'].append(PYTHON_HOME + "/include")
        CONFIG['LIBRARY_DIRS'].append(PYTHON_HOME + "libs")
        CONFIG['LIBRARIES'].append('python%s' % PYTHON_VERSION)
        os.environ['CC'] = 'i586-mingw32msvc-gcc'
except IndexError: pass

# Unfortunately distutils hardcodes compilers etc. We need to monkey
# patch it here to make it work with other compilers.
class Mingw32CCompiler (cygwinccompiler.CygwinCCompiler):

    compiler_type = 'mingw32'

    def __init__ (self,
                  verbose=0,
                  dry_run=0,
                  force=0):

        cygwinccompiler.CygwinCCompiler.__init__ (self, verbose, dry_run, force)

        # ld_version >= "2.13" support -shared so use it instead of
        # -mdll -static
        if self.ld_version >= "2.13":
            shared_option = "-shared"
        else:
            shared_option = "-mdll -static"

        # A real mingw32 doesn't need to specify a different entry point,
        # but cygwin 2.91.57 in no-cygwin-mode needs it.
        if self.gcc_version <= "2.91.57":
            entry_point = '--entry _DllMain@12'
        else:
            entry_point = ''

        self.set_executables(
            compiler=os.environ.get("CC","gcc") + ' -mno-cygwin -O -g -Wall',
            compiler_so=os.environ.get("CC","gcc") + ' -mno-cygwin -mdll -O -g -Wall',
            compiler_cxx=os.environ.get("CC","gcc") + ' -mno-cygwin -O -g -Wall',
            linker_exe=os.environ.get("CC","gcc") + ' -mno-cygwin',
            linker_so='%s -mno-cygwin -g %s %s' % (os.environ.get('CC', self.linker_dll),
                                                shared_option, entry_point))
        # Maybe we should also append -mthreads, but then the finished
        # dlls need another dll (mingwm10.dll see Mingw32 docs)
        # (-mthreads: Support thread-safe exception handling on `Mingw32')

        self.dll_libraries=[]

        # Include the appropriate MSVC runtime library if Python was built
        # with MSVC 7.0 or later.
        if cygwinccompiler.get_msvcr():
            self.dll_libraries += cygwinccompiler.get_msvcr()

    # __init__ ()


# Monkeypatch this:
cygwinccompiler.Mingw32CCompiler = Mingw32CCompiler

# Determine if shared object version of libtalloc is available.
# Try to "use" the talloc_version_major function in libtalloc.
ccompiler = ccompiler.new_compiler()
if ccompiler.has_function('talloc_version_major',libraries=('talloc',)):
    have_libtalloc = True
    CONFIG['LIBRARIES'].append('talloc')
else:
    have_libtalloc = False

# Generate the pytsk3.c code.
BOUND_FILES = ("""
    %(TSK_HEADERS_LOCATION)s/libtsk.h
    %(TSK_HEADERS_LOCATION)s/fs/tsk_fs.h
    %(TSK_HEADERS_LOCATION)s/vs/tsk_vs.h
    %(TSK_HEADERS_LOCATION)s/base/tsk_base.h
    %(TSK_HEADERS_LOCATION)s/img/tsk_img.h
    tsk3.h
    """ % CONFIG).split()

if not os.access("pytsk3.c", os.F_OK):
    generate_bindings("pytsk3.c", BOUND_FILES, initialization='tsk_init();' )

# Set up the python extension.
PYTSK_SOURCES = ['class.c', 'error.c', 'pytsk3.c', 'tsk3.c']
TALLOC_SOURCES = ['talloc/replace.c', 'talloc/talloc.c']

if not have_libtalloc:
    PYTSK_SOURCES += TALLOC_SOURCES

setup(name='pytsk3',
      version='0.1',
      description = "Python bindings for the sleuthkit",
      author = "Michael Cohen",
      author_email = "scudette@gmail.com",
      url = "http://code.google.com/p/pytsk/",
      license = "Apache 2.0",
      long_description = "Python bindings for the sleuthkit (http://www.sleuthkit.org/)",
      ext_modules=[Extension('pytsk3', PYTSK_SOURCES,
                             include_dirs=CONFIG['HEADERS'],
                             libraries=CONFIG['LIBRARIES'],
                             library_dirs = CONFIG['LIBRARY_DIRS'],
                             define_macros = CONFIG['DEFINES'],
                             )
                   ],
      )
