#!/usr/bin/python
#
# Copyright 2010, Michael Cohen <scudette@gmail.com>.
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

import glob
import os
import platform
import sys

from distutils import ccompiler
from distutils import cygwinccompiler
from distutils import sysconfig

try:
  from setuptools import setup, Command, Extension
except ImportError:
  from distutils.core import setup, Command, Extension

try:
  from setuptools.commands.bdist_rpm import bdist_rpm
except ImportError:
  from distutils.command.bdist_rpm import bdist_rpm

import generate_bindings
import run_tests


class BdistRPMCommand(bdist_rpm):
  """Custom handler for the bdist_rpm command."""

  def _make_spec_file(self):
    """Generates the text of an RPM spec file.

    Returns:
      A list of strings containing the lines of text.
    """
    global TSK_VERSION, PYTSK_VERSION

    # Note that bdist_rpm can be an old style class.
    if issubclass(BdistRPMCommand, object):
      spec_file = super(BdistRPMCommand, self)._make_spec_file()
    else:
      spec_file = bdist_rpm._make_spec_file(self)

    if sys.version_info[0] < 3:
      python_package = "python"
    else:
      python_package = "python3"

    description = []
    summary = ""
    in_description = False

    python_spec_file = []
    for index, line in enumerate(spec_file):
      if line.startswith("Summary: "):
        summary = line

      elif line.startswith("%define unmangled_version "):
        line = "%define unmangled_version {0:s}-{1:s}".format(
            TSK_VERSION, PYTSK_VERSION)

      elif line.startswith("BuildRequires: "):
        line = "BuildRequires: {0:s}-setuptools".format(python_package)

      elif line.startswith('Requires: '):
        if python_package == 'python3':
          line = line.replace('python', 'python3')

      elif line.startswith("%description"):
        in_description = True

      elif line.startswith("%files"):
        line = "%files -f INSTALLED_FILES {0:s}".format(
           python_package)

      elif line.startswith("%prep"):
        in_description = False

        python_spec_file.append(
            "%package {0:s}".format(python_package))
        python_spec_file.append("{0:s}".format(summary))
        python_spec_file.append("")
        python_spec_file.append(
            "%description {0:s}".format(python_package))
        python_spec_file.extend(description)

      elif in_description:
        # Ignore leading white lines in the description.
        if not description and not line:
          continue

        description.append(line)

      python_spec_file.append(line)

    return python_spec_file


class TestCommand(Command):
  """Command to run tests."""
  user_options = []

  def initialize_options(self):
    self._dir = os.getcwd()

  def finalize_options(self):
    pass

  def run(self):
    test_results = run_tests.RunTests(os.path.join(".", "tests"))


# Unfortunately distutils hardcodes compilers etc. We need to monkey
# patch it here to make it work with other compilers.
class Mingw32CCompiler(cygwinccompiler.CygwinCCompiler):
  compiler_type = "mingw32"

  def __init__ (self, verbose=0, dry_run=0, force=0):
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
      entry_point = "--entry _DllMain@12"
    else:
      entry_point = ""

    compiler = os.environ.get("CC", "gcc") + " -mno-cygwin -O -g -Wall"
    compiler_so = os.environ.get("CC", "gcc") + " -mno-cygwin -mdll -O -g -Wall"
    compiler_cxx = os.environ.get("CC", "gcc") + " -mno-cygwin -O -g -Wall"
    linker_exe = os.environ.get("CC", "gcc") + " -mno-cygwin"
    linker_so = "{0:s} -mno-cygwin -g {1:s} {2:s}".format(
        os.environ.get("CC", self.linker_dll), shared_option, entry_point)

    self.set_executables(
        compiler=compiler, compiler_so=compiler_so, compiler_cxx=compiler_cxx,
        linker_exe=linker_exe, linker_so=linker_so)

    # Maybe we should also append -mthreads, but then the finished
    # dlls need another dll (mingwm10.dll see Mingw32 docs)
    # (-mthreads: Support thread-safe exception handling on "Mingw32")

    self.dll_libraries = []

    # Include the appropriate MSVC runtime library if Python was built
    # with MSVC 7.0 or later.
    if cygwinccompiler.get_msvcr():
      self.dll_libraries += cygwinccompiler.get_msvcr()


# Determine the location of the SleuthKit include header files.
TSK_HEADERS_PATH = None

results = glob.glob(os.path.join("/", "usr", "include", "tsk*"))
relative_path = False

if len(results) == 0:
  results = glob.glob(os.path.join("/", "usr", "local", "include", "tsk*"))

# If the headers are not found in the usual places check the parent directory.
if len(results) == 0:
  results = glob.glob(os.path.join("..", "sleuthkit*", "tsk*"))
  relative_path = True

if len(results) == 1:
  if results[0].endswith("tsk3"):
    TSK_HEADERS_PATH = results[0]
    TSK_HEADERS_SUBDIR = "tsk3"

  # SleuthKit 4.1 changed the names of the include headers and the library.
  elif results[0].endswith("tsk"):
    TSK_HEADERS_PATH = results[0]
    TSK_HEADERS_SUBDIR = "tsk"

if not TSK_HEADERS_PATH or not os.path.exists(TSK_HEADERS_PATH):
  raise EnvironmentError("Unable to locate SleuthKit header files.")

# Remove the headers sub directory from the headers path.
TSK_HEADERS_PATH = os.path.dirname(TSK_HEADERS_PATH)

print("Sleuthkit headers found in: {0:s}".format(TSK_HEADERS_PATH))

# Determine the SleuthKit version from base/tsk_base.h,
# from: #define TSK_VERSION_STR "4.1.0"
TSK_VERSION = None

file_object = open(os.path.join(
    TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "base", "tsk_base.h"))

for line in file_object.readlines():
  if line.startswith("#define TSK_VERSION_STR \""):
    TSK_VERSION = line[25:30]
    break

file_object.close()

if not TSK_VERSION:
  raise EnvironmentError("Unable to determine SleuthKit version.")

print("Sleuthkit version found: {0:s}".format(TSK_VERSION))

PYTSK_VERSION = None

file_object = open("class_parser.py")

for line in file_object.readlines():
  line = line.rstrip()
  if line.startswith("VERSION = \"") and line.endswith("\""):
    PYTSK_VERSION = line[11:-1]
    break

file_object.close()

if not PYTSK_VERSION:
  raise EnvironmentError("Unable to determine pytsk version.")

print("Pytsk version found: {0:s}".format(PYTSK_VERSION))

# Command bdist_msi does not support the SleuthKit version followed by
# the pytsk version.
if "bdist_msi" in sys.argv:
  MODULE_VERSION = TSK_VERSION
elif "bdist_rpm" in sys.argv:
  MODULE_VERSION = "{0:s}_{1:s}".format(TSK_VERSION, PYTSK_VERSION)
elif "sdist" in sys.argv:
  MODULE_VERSION = "{0:s}".format(PYTSK_VERSION)
else:
  MODULE_VERSION = "{0:s}-{1:s}".format(TSK_VERSION, PYTSK_VERSION)

# Set-up the build configuration.
CONFIG = dict(
    LIBRARY_DIRS = [],
    LIBRARIES = [],
    DEFINES = [])

CONFIG["HEADERS"] = [TSK_HEADERS_PATH]

if platform.system() == "Windows":
  if TSK_HEADERS_SUBDIR == "tsk3":
    CONFIG["LIBRARIES"].append("libauxtools")
    CONFIG["LIBRARIES"].append("libfstools")
    CONFIG["LIBRARIES"].append("libimgtools")
    CONFIG["LIBRARIES"].append("libmmtools")
    CONFIG["DEFINES"].append(("HAVE_TSK3_LIBTSK_H", None))

  # SleuthKit 4.1 changed the names of the include headers and the library.
  elif TSK_HEADERS_SUBDIR == "tsk":
    CONFIG["LIBRARIES"].append("libtsk")
    CONFIG["DEFINES"].append(("HAVE_TSK_LIBTSK_H", None))

  CONFIG["DEFINES"].append(("WIN32", None))

  CONFIG["LIBRARY_DIRS"].append(os.path.join("msvscpp", "Release"))

  # Find the SleuthKit libraries path.
  results = glob.glob(os.path.join(
      TSK_HEADERS_PATH, "win32", "Release",
      "{0:s}.lib".format(CONFIG["LIBRARIES"][0])))

  if len(results) == 0:
    results = glob.glob(os.path.join(
        TSK_HEADERS_PATH, "win32", "x64", "Release",
        "{0:s}.lib".format(CONFIG["LIBRARIES"][0])))

  if len(results) == 0:
    results = glob.glob(os.path.join(
        TSK_HEADERS_PATH, "vs2008", "Release",
        "{0:s}.lib".format(CONFIG["LIBRARIES"][0])))

  if len(results) == 1:
    TSK_LIBRARIES_PATH = os.path.dirname(results[0])
  else:
    TSK_LIBRARIES_PATH = None

  if not TSK_LIBRARIES_PATH or not os.path.exists(TSK_LIBRARIES_PATH):
    raise EnvironmentError("Unable to locate SleuthKit libraries path.")

  CONFIG["LIBRARY_DIRS"].append(TSK_LIBRARIES_PATH)

else:
  if TSK_HEADERS_SUBDIR == "tsk3":
    CONFIG["LIBRARIES"] = ["tsk3"]
    CONFIG["DEFINES"] = [("HAVE_TSK3_LIBTSK_H", None)]

  # SleuthKit 4.1 changed the names of the include headers and the library.
  elif TSK_HEADERS_SUBDIR == "tsk":
    CONFIG["LIBRARIES"] = ["tsk"]
    CONFIG["DEFINES"] = [("HAVE_TSK_LIBTSK_H", None)]

  if relative_path:
    TSK_LIBRARIES_PATH = os.path.join(
        TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, ".libs")

  else:
    tsk_library_base_path = os.path.dirname(TSK_HEADERS_PATH)

    TSK_LIBRARIES_PATH = os.path.join(tsk_library_base_path, "lib")

    if not os.path.exists(TSK_LIBRARIES_PATH):
      TSK_LIBRARIES_PATH = os.path.join(tsk_library_base_path, "lib64")

  if not os.path.exists(TSK_LIBRARIES_PATH):
    raise EnvironmentError("Unable to locate SleuthKit libraries path.")

  CONFIG["LIBRARY_DIRS"].append(TSK_LIBRARIES_PATH)

  # On non-Windows platforms the inclusion of libstdc++ needs to forced,
  # because some builds of the SleuthKit forget to explicitly link against it.
  CONFIG["LIBRARIES"].append("stdc++")

# Used by MinGW/Wine cross compilation.
PYTHON_VERSION = "27"
PYTHON_HOME = "{0:s}/.wine/drive_c/Python{1:s}/".format(
    os.environ.get("HOME", ""), PYTHON_VERSION)

# This is so horrible but less horrible than interfering with distutils.
if len(sys.argv) > 1 and sys.argv[1] == "mingw-xcompile":
  sys.argv[1] = "build"
  sys.argv.extend(("-c", "mingw32"))
  sysconfig._init_nt()
  CONFIG["HEADERS"].append(PYTHON_HOME + "/include")
  CONFIG["LIBRARY_DIRS"].append(PYTHON_HOME + "libs")
  CONFIG["LIBRARIES"].append("python{0:s}".format(PYTHON_VERSION))
  os.environ["CC"] = "i586-mingw32msvc-gcc"

  # Monkeypatch this:
  cygwinccompiler.Mingw32CCompiler = Mingw32CCompiler

# Determine if shared object version of libtalloc is available.
# Try to "use" the talloc_version_major function in libtalloc.
ccompiler = ccompiler.new_compiler()
if ccompiler.has_function("talloc_version_major", libraries=("talloc", )):
  have_libtalloc = True
  CONFIG["LIBRARIES"].append("talloc")
else:
  have_libtalloc = False

# Generate the pytsk3.c code.
BOUND_FILES = [
    os.path.join(TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "libtsk.h"),
    os.path.join(TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "base", "tsk_base.h"),
    os.path.join(TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "fs", "tsk_fs.h"),
    os.path.join(TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "img", "tsk_img.h"),
    os.path.join(TSK_HEADERS_PATH, TSK_HEADERS_SUBDIR, "vs", "tsk_vs.h"),
    "tsk3.h"]

if not os.access("pytsk3.c", os.F_OK):
  generate_bindings.generate_bindings(
      "pytsk3.c", BOUND_FILES, initialization="tsk_init();")

# Set up the python extension.
PYTSK_SOURCES = ["class.c", "error.c", "pytsk3.c", "tsk3.c"]
TALLOC_SOURCES = ["talloc/talloc.c"]

if not have_libtalloc:
  PYTSK_SOURCES += TALLOC_SOURCES
  CONFIG["HEADERS"].append("talloc")
  CONFIG["LIBRARY_DIRS"].append("talloc")

setup(
    name="pytsk3",
    version=MODULE_VERSION,
    description = "Python bindings for the sleuthkit",
    long_description = (
        "Python bindings for the sleuthkit (http://www.sleuthkit.org/)"),
    license = "Apache 2.0",
    url = "https://github.com/py4n6/pytsk/",
    author = "Michael Cohen",
    author_email = "scudette@gmail.com",
    cmdclass={
        'bdist_rpm': BdistRPMCommand,
        'test': TestCommand},
    ext_modules = [
        Extension(
            "pytsk3",
            PYTSK_SOURCES,
            include_dirs = CONFIG["HEADERS"],
            libraries = CONFIG["LIBRARIES"],
            library_dirs = CONFIG["LIBRARY_DIRS"],
            define_macros = CONFIG["DEFINES"],
        )
    ],
    data_files=[
        ("share/doc/pytsk", ["LICENSE", "README"]),
    ],
)
