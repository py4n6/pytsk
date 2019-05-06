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

import glob
import re
import os
import subprocess
import sys
import time

import distutils.ccompiler

from distutils.ccompiler import new_compiler
from setuptools import setup, Command, Extension
from setuptools.command.build_ext import build_ext
from setuptools.command.sdist import sdist

try:
  from distutils.command.bdist_msi import bdist_msi
except ImportError:
  bdist_msi = None

try:
  from distutils.command.bdist_rpm import bdist_rpm
except ImportError:
  bdist_rpm = None

import generate_bindings
import run_tests


if not bdist_msi:
  BdistMSICommand = None
else:
  class BdistMSICommand(bdist_msi):
    """Custom handler for the bdist_msi command."""

    def run(self):
      """Builds an MSI."""
      # Command bdist_msi does not support the library version, neither a date
      # as a version but if we suffix it with .1 everything is fine.
      self.distribution.metadata.version += ".1"

      bdist_msi.run(self)


if not bdist_rpm:
  BdistRPMCommand = None
else:
  class BdistRPMCommand(bdist_rpm):
    """Custom handler for the bdist_rpm command."""

    def make_spec_file(self, spec_file):
      """Make an RPM Spec file."""
      # Note that bdist_rpm can be an old style class.
      if issubclass(BdistRPMCommand, object):
        spec_file = super(BdistRPMCommand, self)._make_spec_file()
      else:
        spec_file = bdist_rpm._make_spec_file(self)

      if sys.version_info[0] < 3:
        python_package = 'python2'
      else:
        python_package = 'python3'

      description = []
      requires = ''
      summary = ''
      in_description = False

      python_spec_file = []
      for line in iter(spec_file):
        if line.startswith('Summary: '):
          summary = line

        elif line.startswith('BuildRequires: '):
          line = 'BuildRequires: {0:s}-setuptools, {0:s}-devel'.format(
              python_package)

        elif line.startswith('Requires: '):
          requires = line[10:]
          if python_package == 'python3':
            requires = requires.replace('python-', 'python3-')
            requires = requires.replace('python2-', 'python3-')

        elif line.startswith('%description'):
          in_description = True

        elif line.startswith('python setup.py build'):
          if python_package == 'python3':
            line = '%py3_build'
          else:
            line = '%py2_build'

        elif line.startswith('python setup.py install'):
          if python_package == 'python3':
            line = '%py3_install'
          else:
            line = '%py2_install'

        elif line.startswith('%files'):
          lines = [
              '%files -n {0:s}-%{{name}}'.format(python_package),
              '%defattr(644,root,root,755)',
              '%license LICENSE',
              '%doc README']

          if python_package == 'python3':
            lines.extend([
                '%{_libdir}/python3*/site-packages/*.so',
                '%{_libdir}/python3*/site-packages/pytsk3*.egg-info/*',
                '',
                '%exclude %{_prefix}/share/doc/*'])

          else:
            lines.extend([
                '%{_libdir}/python2*/site-packages/*.so',
                '%{_libdir}/python2*/site-packages/pytsk3*.egg-info/*',
                '',
                '%exclude %{_prefix}/share/doc/*'])

          python_spec_file.extend(lines)
          break

        elif line.startswith('%prep'):
          in_description = False

          python_spec_file.append(
              '%package -n {0:s}-%{{name}}'.format(python_package))
          if python_package == 'python2':
            python_spec_file.extend([
                'Obsoletes: python-pytsk3 < %{version}',
                'Provides: python-pytsk3 = %{version}'])

          if requires:
            python_spec_file.append('Requires: {0:s}'.format(requires))

          python_spec_file.extend([
              '{0:s}'.format(summary),
              '',
              '%description -n {0:s}-%{{name}}'.format(python_package)])

          python_spec_file.extend(description)

        elif in_description:
          # Ignore leading white lines in the description.
          if not description and not line:
            continue

          description.append(line)

        python_spec_file.append(line)

      return python_spec_file

    def _make_spec_file(self):
      """Generates the text of an RPM spec file.

      Returns:
        list[str]: lines of text.
      """
      return self.make_spec_file(
          bdist_rpm._make_spec_file(self))


class BuildExtCommand(build_ext):
  """Custom handler for the build_ext command."""

  def configure_source_tree(self, compiler):
    """Configures the source and returns a dict of defines."""
    define_macros = []
    define_macros.append(("HAVE_TSK_LIBTSK_H", ""))

    if compiler.compiler_type == "msvc":
      return define_macros + [
          ("WIN32", "1"),
          ("UNICODE", "1"),
          ("_CRT_SECURE_NO_WARNINGS", "1"),
      ]

    # We want to build as much as possible self contained Python
    # binding.
    command = [
        "sh", "configure", "--disable-java", "--without-afflib",
        "--without-libewf", "--without-libpq", "--without-libvhdi",
        "--without-libvmdk", "--without-zlib"]

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

    return define_macros + [
        ("HAVE_CONFIG_H", "1"),
        ("LOCALEDIR", "\"/usr/share/locale\""),
    ]

  def run(self):
    compiler = new_compiler(compiler=self.compiler)
    # pylint: disable=attribute-defined-outside-init
    self.define = self.configure_source_tree(compiler)

    libtsk_path = os.path.join("sleuthkit", "tsk")

    if not os.access("pytsk3.c", os.R_OK):
      # Generate the Python binding code (pytsk3.c).
      libtsk_header_files = [
          os.path.join(libtsk_path, "libtsk.h"),
          os.path.join(libtsk_path, "base", "tsk_base.h"),
          os.path.join(libtsk_path, "fs", "tsk_fs.h"),
          os.path.join(libtsk_path, "img", "tsk_img.h"),
          os.path.join(libtsk_path, "vs", "tsk_vs.h"),
          "tsk3.h"]

      print("Generating bindings...")
      generate_bindings.generate_bindings(
          "pytsk3.c", libtsk_header_files, initialization="tsk_init();")

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
  _SLEUTHKIT_GIT_TAG = "4.6.6"

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
        "sleuthkit-{0:s}-configure.ac".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-ext2fs.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-ext2fs_dent.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-ffs_dent.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-gpt.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-hfs.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-hfs_dent.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-lzvn.patch".format(self._SLEUTHKIT_GIT_TAG),
        "sleuthkit-{0:s}-ntfs.patch".format(self._SLEUTHKIT_GIT_TAG)]

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
    subprocess.check_call(["git", "checkout", "master"], cwd="sleuthkit")
    subprocess.check_call(["git", "pull"], cwd="sleuthkit")
    if self.use_head:
      print("Pulling from HEAD")
    else:
      print("Pulling from tag: {0:s}".format(self._SLEUTHKIT_GIT_TAG))
      subprocess.check_call(["git", "fetch", "--tags"], cwd="sleuthkit")
      git_tag_path = "tags/sleuthkit-{0:s}".format(self._SLEUTHKIT_GIT_TAG)
      subprocess.check_call(["git", "checkout", git_tag_path], cwd="sleuthkit")

      self.patch_sleuthkit()

    compiler_type = distutils.ccompiler.get_default_compiler()
    if compiler_type != "msvc":
      subprocess.check_call(["./bootstrap"], cwd="sleuthkit")

    # Now derive the version based on the date.
    with open("version.txt", "w") as fd:
      fd.write(self.version)

    libtsk_path = os.path.join("sleuthkit", "tsk")

    # Generate the Python binding code (pytsk3.c).
    libtsk_header_files = [
        os.path.join(libtsk_path, "libtsk.h"),
        os.path.join(libtsk_path, "base", "tsk_base.h"),
        os.path.join(libtsk_path, "fs", "tsk_fs.h"),
        os.path.join(libtsk_path, "img", "tsk_img.h"),
        os.path.join(libtsk_path, "vs", "tsk_vs.h"),
        "tsk3.h"]

    print("Generating bindings...")
    generate_bindings.generate_bindings(
        "pytsk3.c", libtsk_header_files, initialization="tsk_init();")


class ProjectBuilder(object):
  """Class to help build the project."""

  def __init__(self, project_config, argv):
    """Initializes a project builder object."""
    self._project_config = project_config
    self._argv = argv

    # The path to the sleuthkit/tsk directory.
    self._libtsk_path = os.path.join("sleuthkit", "tsk")

    # Paths under the sleuthkit/tsk directory which contain files we need
    # to compile.
    self._sub_library_names = [
        "auto", "base", "docs", "fs", "hashdb", "img", "vs"]

    # The args for the extension builder.
    self.extension_args = {
        "define_macros": [],
        "include_dirs": ["talloc", self._libtsk_path, "sleuthkit", "."],
        "library_dirs": [],
        "libraries": []}

    # The sources to build.
    self._source_files = [
        "class.c", "error.c", "tsk3.c", "pytsk3.c", "talloc/talloc.c"]

    # Path to the top of the unpacked sleuthkit sources.
    self._sleuthkit_path = "sleuthkit"

  def build(self):
    """Build everything."""
    # Fetch all c and cpp files from the subdirs to compile.
    for library_name in self._sub_library_names:
      for extension in ("*.c", "*.cpp"):
        extension_glob = os.path.join(
            self._libtsk_path, library_name, extension)
        self._source_files.extend(glob.glob(extension_glob))

    # Sort the soure files to make sure they are in consistent order when
    # building.
    source_files = sorted(self._source_files)
    ext_modules = [Extension("pytsk3", source_files, **self.extension_args)]

    setup(
        cmdclass={
            "build_ext": BuildExtCommand,
            "bdist_msi": BdistMSICommand,
            "bdist_rpm": BdistRPMCommand,
            "sdist": SDistCommand,
            "update": UpdateCommand},
        ext_modules=ext_modules,
        **self._project_config)


if __name__ == "__main__":
  __version__ = open("version.txt").read().strip()

  setup_args = dict(
      name="pytsk3",
      version=__version__,
      description="Python bindings for the sleuthkit",
      long_description=(
          "Python bindings for the sleuthkit (http://www.sleuthkit.org/)"),
      license="Apache 2.0",
      url="https://github.com/py4n6/pytsk/",
      author="Michael Cohen and Joachim Metz",
      author_email="scudette@gmail.com, joachim.metz@gmail.com",
      zip_safe=False)

  ProjectBuilder(setup_args, sys.argv).build()
