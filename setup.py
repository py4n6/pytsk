#!/usr/bin/python

from distutils.core import setup, Extension
from distutils import sysconfig
import class_parser
import sys
import os
import pdb

# Distutils is retarded - We need to monkey patch it to make it saner.
from distutils import cygwinccompiler

PYTHON_HOME = "/home/scudette/.wine/drive_c/Python26/"

CONFIG = dict(TSK3_HEADER_LOCATION = "/usr/local/include/tsk3/",
              LIBRARY_DIRS = [],
              LIBRARIES = ['tsk3'])

CONFIG['HEADERS'] = [CONFIG['TSK3_HEADER_LOCATION']]

# This is so horrible but less horrible than interfering with
# distutils
try:
    if sys.argv[1] == "mingw-xcompile":
        sys.argv[1] = "build"
        sys.argv.extend(("-c", "mingw32"))
        sysconfig._init_nt()
        CONFIG['HEADERS'].append(PYTHON_HOME + "/include")
        CONFIG['LIBRARY_DIRS'].append(PYTHON_HOME + "libs")
        CONFIG['LIBRARIES'].append('python26')
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

SOURCES = ['tsk3.c', 'class.c', 'pytsk3.c', 'talloc.c', 'error.c', 'replace.c']

setup(name='pytsk3',
      version='0.1',
      description = "Python bindings for the sluethkit",
      author = "Michael Cohen",
      author_email = "scudette@gmail.com",
      url = "http://code.google.com/p/pytsk/",
      license = "Apache 2.0",
      long_description = "Python bindings for the sluethkit (http://www.sleuthkit.org/)",
      ext_modules=[Extension('pytsk3', SOURCES,
                             include_dirs=CONFIG['HEADERS'],
                             libraries=CONFIG['LIBRARIES'],
                             library_dirs = CONFIG['LIBRARY_DIRS'],
                             )
                   ],
      )
