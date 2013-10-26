#!/usr/bin/python

import glob
import os
import platform
import sys

from distutils.core import setup, Extension
from distutils import ccompiler, sysconfig

import class_parser
from generate_bindings import *

import pdb

# Distutils is retarded - We need to monkey patch it to make it saner.
from distutils import cygwinccompiler


# Determine the location of the SleuthKit include header files.
TSK_HEADERS_PATH = None

results = glob.glob(os.path.join('/', 'usr', 'include', 'tsk*'))
relative_path = False

if len(results) == 0:
    results = glob.glob(os.path.join('/', 'usr', 'local', 'include', 'tsk*'))

# If the headers are not found in the usual places check the parent directory.
if len(results) == 0:
    results = glob.glob(os.path.join('..', 'sleuthkit*', 'tsk*'))
    relative_path = True

if len(results) == 1:
    if results[0].endswith('tsk3'):
        TSK_HEADERS_PATH = results[0]

    # SleuthKit 4.1 changed the names of the include headers and the library.
    elif results[0].endswith('tsk'):
        TSK_HEADERS_PATH = results[0]

if not TSK_HEADERS_PATH or not os.path.exists(TSK_HEADERS_PATH):
    raise EnvironmentError('Unable to locate SleuthKit header files.')

print 'Sleuthkit headers found in: %s' % TSK_HEADERS_PATH

# Determine the SleuthKit version from base/tsk_base.h,
# from: #define TSK_VERSION_STR "4.1.0"
TSK_VERSION = None

file_object = open(os.path.join(
    TSK_HEADERS_PATH, 'base', 'tsk_base.h'))

for line in file_object.readlines():
    if line.startswith('#define TSK_VERSION_STR "'):
        TSK_VERSION = line[25:30]
        break

file_object.close()

if not TSK_VERSION:
    raise EnvironmentError('Unable to determine SleuthKit version.')

print 'Sleuthkit version found: %s' % TSK_VERSION

# Set-up the build configuration.
CONFIG = dict(
    LIBRARY_DIRS = [],
    LIBRARIES = [],
    DEFINES = [])

CONFIG['HEADERS'] = [TSK_HEADERS_PATH]

# For a relative SleuthKit header files location we need to include
# its parent directory.
TSK_PATH = os.path.dirname(TSK_HEADERS_PATH)

if relative_path:
    CONFIG['HEADERS'].append(TSK_PATH)

if platform.system() == 'Windows':
    if TSK_HEADERS_PATH.endswith('tsk3'):
        CONFIG['LIBRARIES'].append('libauxtools')
        CONFIG['LIBRARIES'].append('libfstools')
        CONFIG['LIBRARIES'].append('libimgtools')
        CONFIG['LIBRARIES'].append('libmmtools')
        CONFIG['DEFINES'].append(('HAVE_TSK3_LIBTSK_H', None))

    # SleuthKit 4.1 changed the names of the include headers and the library.
    elif TSK_HEADERS_PATH.endswith('tsk'):
        CONFIG['LIBRARIES'].append('libtsk')
        CONFIG['DEFINES'].append(('HAVE_TSK_LIBTSK_H', None))

    CONFIG['DEFINES'].append(('WIN32', None))

    CONFIG['LIBRARY_DIRS'].append(os.path.join('msvscpp', 'Release'))

    # Find the SleuthKit libraries path.
    results = glob.glob(os.path.join(
        TSK_PATH, 'win32', 'Release', '%s.lib' % CONFIG['LIBRARIES'][0]))

    if len(results) == 0:
        results = glob.glob(os.path.join(
            TSK_PATH, 'win32', 'x64', 'Release', '%s.lib' % CONFIG['LIBRARIES'][0]))

    if len(results) == 0:
        results = glob.glob(os.path.join(
            TSK_PATH, 'vs2008', 'Release', '%s.lib' % CONFIG['LIBRARIES'][0]))

    if len(results) == 1:
        TSK_LIBRARIES_PATH = os.path.dirname(results[0])
    else:
        TSK_LIBRARIES_PATH = None

    if not TSK_LIBRARIES_PATH or not os.path.exists(TSK_LIBRARIES_PATH):
        raise EnvironmentError('Unable to locate SleuthKit libraries path.')

    CONFIG['LIBRARY_DIRS'].append(TSK_LIBRARIES_PATH)

else:
    if TSK_HEADERS_PATH.endswith('tsk3'):
        CONFIG['LIBRARIES'] = ['tsk3']
        CONFIG['DEFINES'] = [('HAVE_TSK3_LIBTSK_H', None)]

    # SleuthKit 4.1 changed the names of the include headers and the library.
    elif TSK_HEADERS_PATH.endswith('tsk'):
        CONFIG['LIBRARIES'] = ['tsk']
        CONFIG['DEFINES'] = [('HAVE_TSK_LIBTSK_H', None)]

    # On non-Windows platforms the inclusion of libstdc++ needs to forced,
    # because some builds of the SleuthKit forget to explicitly link against it.
    CONFIG['LIBRARIES'].append('stdc++')

# Used by MinGW/Wine cross compilation.
PYTHON_VERSION = '27'
PYTHON_HOME = '%s/.wine/drive_c/Python%s/' % (
    os.environ.get('HOME', ''), PYTHON_VERSION)

# This is so horrible but less horrible than interfering with distutils.
try:
    if sys.argv[1] == 'mingw-xcompile':
        sys.argv[1] = 'build'
        sys.argv.extend(('-c', 'mingw32'))
        sysconfig._init_nt()
        CONFIG['HEADERS'].append(PYTHON_HOME + '/include')
        CONFIG['LIBRARY_DIRS'].append(PYTHON_HOME + 'libs')
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

        # ld_version >= '2.13' support -shared so use it instead of
        # -mdll -static
        if self.ld_version >= '2.13':
            shared_option = '-shared'
        else:
            shared_option = '-mdll -static'

        # A real mingw32 doesn't need to specify a different entry point,
        # but cygwin 2.91.57 in no-cygwin-mode needs it.
        if self.gcc_version <= '2.91.57':
            entry_point = '--entry _DllMain@12'
        else:
            entry_point = ''

        self.set_executables(
            compiler=os.environ.get('CC', 'gcc') + ' -mno-cygwin -O -g -Wall',
            compiler_so=os.environ.get('CC', 'gcc') + ' -mno-cygwin -mdll -O -g -Wall',
            compiler_cxx=os.environ.get('CC', 'gcc') + ' -mno-cygwin -O -g -Wall',
            linker_exe=os.environ.get('CC', 'gcc') + ' -mno-cygwin',
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
# Try to 'use' the talloc_version_major function in libtalloc.
ccompiler = ccompiler.new_compiler()
if ccompiler.has_function('talloc_version_major',libraries=('talloc',)):
    have_libtalloc = True
    CONFIG['LIBRARIES'].append('talloc')
else:
    have_libtalloc = False

# Generate the pytsk3.c code.
BOUND_FILES = [
   '%s/libtsk.h' % TSK_HEADERS_PATH,
   '%s/fs/tsk_fs.h' % TSK_HEADERS_PATH,
   '%s/vs/tsk_vs.h' % TSK_HEADERS_PATH,
   '%s/base/tsk_base.h' % TSK_HEADERS_PATH,
   '%s/img/tsk_img.h' % TSK_HEADERS_PATH,
   'tsk3.h']

if not os.access('pytsk3.c', os.F_OK):
    generate_bindings('pytsk3.c', BOUND_FILES, initialization='tsk_init();' )

# Set up the python extension.
PYTSK_SOURCES = ['class.c', 'error.c', 'pytsk3.c', 'tsk3.c']
TALLOC_SOURCES = ['talloc/talloc.c']

if not have_libtalloc:
    PYTSK_SOURCES += TALLOC_SOURCES
    CONFIG['HEADERS'].append('talloc')

setup(name='pytsk3',
      version=TSK_VERSION,
      description = 'Python bindings for the sleuthkit',
      author = 'Michael Cohen',
      author_email = 'scudette@gmail.com',
      url = 'http://code.google.com/p/pytsk/',
      license = 'Apache 2.0',
      long_description = 'Python bindings for the sleuthkit (http://www.sleuthkit.org/)',
      ext_modules = [Extension('pytsk3', PYTSK_SOURCES,
                               include_dirs = CONFIG['HEADERS'],
                               libraries = CONFIG['LIBRARIES'],
                               library_dirs = CONFIG['LIBRARY_DIRS'],
                               define_macros = CONFIG['DEFINES'],
                               )
                    ],
      )
