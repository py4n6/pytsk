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
"""Install the pytsk python module.

You can control the installation process using the following environment
variables:

SLEUTHKIT_SOURCE: The path to the locally downloaded tarball of the
  sleuthkit. If not specified we download from the internet.

SLEUTHKIT_PATH: A path to the locally build sleuthkit source tree. If not
  specified we use SLEUTHKIT_SOURCE environment variable (above).

"""

from __future__ import print_function

import copy
import glob
import re
import os
import subprocess
import sys
import time

from setuptools import setup, Command, Extension
from setuptools.command.build_ext import build_ext
from setuptools.command.sdist import sdist

import distutils.ccompiler

from distutils import log
from distutils.ccompiler import new_compiler
from distutils.dep_util import newer_group

# Change PYTHONPATH.
sys.path.insert(0, '.')

import generate_bindings


version_tuple = (sys.version_info[0], sys.version_info[1])
if version_tuple < (3, 7):
  print((
      'Unsupported Python version: {0:s}, version 3.7 or higher '
      'required.').format(sys.version))
  sys.exit(1)


class BuildExtCommand(build_ext):
  """Custom handler for the build_ext command."""

  def build_extension(self, extension):
    """Builds the extension.

    Args:
      extension: distutils extension object.
    """
    if (extension.sources is None or
        not isinstance(extension.sources, (list, tuple))):
      raise errors.DistutilsSetupError((
          'in \'ext_modules\' option (extension \'{0:s}\'), '
          '\'sources\' must be present and must be '
          'a list of source filenames').format(extension.name))

    extension_path = self.get_ext_fullpath(extension.name)
    depends = extension.sources + extension.depends
    if not (self.force or newer_group(depends, extension_path, 'newer')):
      log.debug('skipping \'%s\' extension (up-to-date)', extension.name)
      return

    log.info('building \'%s\' extension', extension.name)

    # C and C++ source files need to be compiled seperately otherwise
    # the extension will not build on Mac OS.
    c_sources = []
    cxx_sources = []
    for source in extension.sources:
      if source.endswith('.c'):
        c_sources.append(source)
      else:
        cxx_sources.append(source)

    objects = []
    for lang, sources in (('c', c_sources), ('c++', cxx_sources)):
      extra_args = extension.extra_compile_args or []
      if lang == 'c++':
        if self.compiler.compiler_type == 'msvc':
          extra_args.append('/EHsc')
        else:
          extra_args.append('-std=c++14')

      macros = extension.define_macros[:]
      for undef in extension.undef_macros:
        macros.append((undef,))

      compiled_objects = self.compiler.compile(
          sources,
          output_dir=self.build_temp,
          macros=macros,
          include_dirs=extension.include_dirs,
          debug=self.debug,
          extra_postargs=extra_args,
          depends=extension.depends)

      objects.extend(compiled_objects)

    self._built_objects = objects[:]
    if extension.extra_objects:
      objects.extend(extension.extra_objects)

    extra_args = extension.extra_link_args or []
    # When MinGW32 is used statically link libgcc and libstdc++.
    if self.compiler.compiler_type == 'mingw32':
      extra_args.extend(['-static-libgcc', '-static-libstdc++'])

    # Now link the object files together into a "shared object" --
    # of course, first we have to figure out all the other things
    # that go into the mix.
    if extension.extra_objects:
      objects.extend(extension.extra_objects)
    extra_args = extension.extra_link_args or []

    # Detect target language, if not provided
    language = extension.language or self.compiler.detect_language(sources)

    self.compiler.link_shared_object(
        objects, extension_path,
        libraries=self.get_libraries(extension),
        library_dirs=extension.library_dirs,
        runtime_library_dirs=extension.runtime_library_dirs,
        extra_postargs=extra_args,
        export_symbols=self.get_export_symbols(extension),
        debug=self.debug,
        build_temp=self.build_temp,
        target_lang=language)

  def configure_source(self, compiler):
    """Configures the source.

    Args:
      compiler: distutils compiler object.
    """
    define_macros = [("HAVE_TSK_LIBTSK_H", "")]

    if compiler.compiler_type == "msvc":
      define_macros.extend([
          ("WIN32", "1"),
          ("UNICODE", "1"),
          ("NOMINMAX", "1"),
          ("_CRT_SECURE_NO_WARNINGS", "1")])

      # TODO: ("GUID_WINDOWS", "1"),

    else:
      # We want to build as much as possible self contained Python
      # binding.
      command = [
          "sh", "configure", "--disable-java", "--disable-multithreading",
          "--without-afflib", "--without-libbfio", "--without-libcrypto",
          "--without-libewf", "--without-libvhdi", "--without-libvmdk",
          "--without-libvslvm", "--without-zlib"]

      output = subprocess.check_output(command, cwd="sleuthkit")
      print_line = False
      for line in output.split(b"\n"):
        line = line.rstrip()
        if line == b"configure:":
          print_line = True

        if print_line:
          if sys.version_info[0] >= 3:
            line = line.decode("ascii")
          print(line)

      define_macros.extend([
          ("HAVE_CONFIG_H", "1"),
          ("LOCALEDIR", "\"/usr/share/locale\"")])

      self.libraries = ["stdc++"]

    self.define = define_macros

  def run(self):
    compiler = new_compiler(compiler=self.compiler)
    # pylint: disable=attribute-defined-outside-init
    self.configure_source(compiler)

    libtsk_path = os.path.join("sleuthkit", "tsk")

    if not os.access("pytsk3.cpp", os.R_OK):
      # Generate the Python binding code (pytsk3.cpp).
      libtsk_header_files = [
          os.path.join(libtsk_path, "libtsk.h"),
          os.path.join(libtsk_path, "base", "tsk_base.h"),
          os.path.join(libtsk_path, "fs", "tsk_fs.h"),
          os.path.join(libtsk_path, "img", "tsk_img.h"),
          os.path.join(libtsk_path, "vs", "tsk_vs.h"),
          "tsk3.h"]

      print("Generating bindings...")
      generate_bindings.generate_bindings(
          "pytsk3.cpp", libtsk_header_files, initialization="tsk_init();")

    build_ext.run(self)


class SDistCommand(sdist):
  """Custom handler for generating source dist."""
  def run(self):
    libtsk_path = os.path.join("sleuthkit", "tsk")

    # sleuthkit submodule is not there, probably because this has been
    # freshly checked out.
    if not os.access(libtsk_path, os.R_OK):
      subprocess.check_call(["git", "submodule", "init"])
      subprocess.check_call(["git", "submodule", "update"])

    if not os.path.exists(os.path.join("sleuthkit", "configure")):
      raise RuntimeError(
          "Missing: sleuthkit/configure run 'setup.py build' first.")

    sdist.run(self)


class UpdateCommand(Command):
  """Update sleuthkit source.

  This is normally only run by packagers to make a new release.
  """
  _SLEUTHKIT_GIT_TAG = "4.13.0"

  version = time.strftime("%Y%m%d")

  timezone_minutes, _ = divmod(time.timezone, 60)
  timezone_hours, timezone_minutes = divmod(timezone_minutes, 60)

  # If timezone_hours is -1 %02d will format as -1 instead of -01
  # hence we detect the sign and force a leading zero.
  if timezone_hours < 0:
    timezone_string = "-%02d%02d" % (-timezone_hours, timezone_minutes)
  else:
    timezone_string = "+%02d%02d" % (timezone_hours, timezone_minutes)

  version_pkg = "%s %s" % (
      time.strftime("%a, %d %b %Y %H:%M:%S"), timezone_string)

  user_options = [("use-head", None, (
      "Use the latest version of Sleuthkit checked into git (HEAD) instead of "
      "tag: {0:s}".format(_SLEUTHKIT_GIT_TAG)))]

  def initialize_options(self):
    self.use_head = False

  def finalize_options(self):
    self.use_head = bool(self.use_head)

  files = {
      "sleuthkit/Makefile.am": [
          ("SUBDIRS = .+", "SUBDIRS = tsk"),
      ],
      "class_parser.py": [
          ('VERSION = "[^"]+"', 'VERSION = "%s"' % version),
      ],
      "dpkg/changelog": [
          (r"pytsk3 \([^\)]+\)", "pytsk3 (%s-1)" % version),
          ("(<[^>]+>).+", r"\1  %s" % version_pkg),
      ],
  }

  def patch_sleuthkit(self):
    """Applies patches to the SleuthKit source code."""
    for filename, rules in iter(self.files.items()):
      filename = os.path.join(*filename.split("/"))

      with open(filename, "r") as file_object:
        data = file_object.read()

      for search, replace in rules:
        data = re.sub(search, replace, data)

      with open(filename, "w") as fd:
        fd.write(data)

    patch_files = [
        "sleuthkit-{0:s}-configure.ac".format(self._SLEUTHKIT_GIT_TAG)]

    for patch_file in patch_files:
      patch_file = os.path.join("patches", patch_file)
      if not os.path.exists(patch_file):
        print("No such patch file: {0:s}".format(patch_file))
        continue

      patch_file = os.path.join("..", patch_file)
      subprocess.check_call(["git", "apply", patch_file], cwd="sleuthkit")

  def run(self):
    subprocess.check_call(["git", "stash"], cwd="sleuthkit")

    subprocess.check_call(["git", "submodule", "init"])
    subprocess.check_call(["git", "submodule", "update"])

    print("Updating sleuthkit")
    subprocess.check_call(["git", "reset", "--hard"], cwd="sleuthkit")
    subprocess.check_call(["git", "clean", "-x", "-f", "-d"], cwd="sleuthkit")
    subprocess.check_call(["git", "checkout", "main"], cwd="sleuthkit")
    subprocess.check_call(["git", "pull"], cwd="sleuthkit")
    if self.use_head:
      print("Pulling from HEAD")
    else:
      print("Pulling from tag: {0:s}".format(self._SLEUTHKIT_GIT_TAG))
      subprocess.check_call(["git", "fetch", "--force", "--tags"], cwd="sleuthkit")
      git_tag_path = "tags/sleuthkit-{0:s}".format(self._SLEUTHKIT_GIT_TAG)
      subprocess.check_call(["git", "checkout", git_tag_path], cwd="sleuthkit")

      self.patch_sleuthkit()

    compiler_type = distutils.ccompiler.get_default_compiler()
    if compiler_type != "msvc":
      subprocess.check_call(["./bootstrap"], cwd="sleuthkit")

    # Now derive the version based on the date.
    with open("setup.cfg", "r", encoding="utf-8") as file_object:
      setup_cfg_lines = file_object.readlines()

    with open("setup.cfg", "w", encoding="utf-8") as file_object:
      for line in setup_cfg_lines:
        if line.startswith("version = "):
          line = "version = {0:s}\n".format(self.version)
        file_object.write(line)

    libtsk_path = os.path.join("sleuthkit", "tsk")

    # Generate the Python binding code (pytsk3.cpp).
    libtsk_header_files = [
        os.path.join(libtsk_path, "libtsk.h"),
        os.path.join(libtsk_path, "base", "tsk_base.h"),
        os.path.join(libtsk_path, "fs", "tsk_fs.h"),
        os.path.join(libtsk_path, "img", "tsk_img.h"),
        os.path.join(libtsk_path, "vs", "tsk_vs.h"),
        "tsk3.h"]

    print("Generating bindings...")
    generate_bindings.generate_bindings(
        "pytsk3.cpp", libtsk_header_files, initialization="tsk_init();")


class ProjectBuilder(object):
  """Class to help build the project."""

  def __init__(self, argv):
    """Initializes a project builder object."""
    self._argv = argv

    # The path to the sleuthkit/tsk directory.
    self._libtsk_path = os.path.join("sleuthkit", "tsk")

    # Paths under the sleuthkit/tsk directory which contain files we need
    # to compile.
    self._sub_library_names = ["base", "docs", "fs", "img", "pool", "util", "vs"]

    # The args for the extension builder.
    self.extension_args = {
        "include_dirs": ["talloc", self._libtsk_path, "sleuthkit", "."],
        "library_dirs": []}

    # The sources to build.
    self._source_files = [
        "class.cpp", "error.cpp", "tsk3.cpp", "pytsk3.cpp", "talloc/talloc.c"]

    # Path to the top of the unpacked sleuthkit sources.
    self._sleuthkit_path = "sleuthkit"

  def build(self):
    """Build everything."""
    # Fetch all c and cpp files from the subdirs to compile.
    extension_file = os.path.join(
        self._libtsk_path, "auto", "guid.cpp")
    self._source_files.append(extension_file)

    for library_name in self._sub_library_names:
      for extension in ("*.c", "*.cpp"):
        extension_glob = os.path.join(
            self._libtsk_path, library_name, extension)
        self._source_files.extend(glob.glob(extension_glob))

    # Sort the soure files to make sure they are in consistent order when
    # building.
    source_files = sorted(self._source_files)
    ext_modules = [Extension("pytsk3", source_files, **self.extension_args)]

    setup_args = dict(
        cmdclass={
            "build_ext": BuildExtCommand,
            "sdist": SDistCommand,
            "update": UpdateCommand},
        ext_modules=ext_modules)

    setup(**setup_args)


if __name__ == "__main__":
  ProjectBuilder(sys.argv).build()
