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

from distutils.ccompiler import new_compiler
from setuptools import setup, Command, Extension
from setuptools.command.build_ext import build_ext
from setuptools.command.sdist import sdist
from setuptools.command.bdist_rpm import bdist_rpm

import generate_bindings
import run_tests


__version__ = open("version.txt").read().strip()

# Command bdist_msi does not support the library version, neither a date
# as a version but if we suffix it with .1 everything is fine.
if 'bdist_msi' in sys.argv:
  __version__ += '.1'

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
    zip_safe=False,
)


class BdistRPMCommand(bdist_rpm):
    """Custom handler for the bdist_rpm command."""

    def make_spec_file(self, spec_file):
        """Make an RPM Spec file."""
        if sys.version_info[0] < 3:
            python_package = "python"
        else:
            python_package = "python3"

        description = []
        summary = ""
        in_description = False

        python_spec_file = []
        for line in spec_file:
            if line.startswith("Summary: "):
                summary = line

            elif line.startswith("BuildRequires: "):
                line = "BuildRequires: {0}-setuptools".format(python_package)

            elif line.startswith('Requires: '):
                if python_package == 'python3':
                    line = line.replace('python', 'python3')

            elif line.startswith("%description"):
                in_description = True

            elif line.startswith("%files"):
                line = "%files -f INSTALLED_FILES {0}".format(
                    python_package)

            elif line.startswith("%prep"):
                in_description = False

                python_spec_file.append(
                    "%package {0}".format(python_package))
                python_spec_file.append("{0}".format(summary))
                python_spec_file.append("")
                python_spec_file.append(
                    "%description {0}".format(python_package))
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
          A list of strings containing the lines of text.
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
            ]

        # We want to build as much as possible self contained Python
        # binding.
        command = ["sh", "configure", "--disable-java", "--without-afflib",
                   "--without-libewf", "--without-zlib"]

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
        self.define = self.configure_source_tree(compiler)

        libtsk_path = "sleuthkit/tsk"

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
        libtsk_path = "sleuthkit/tsk"

        # sleuthkit submodule is not there, probably because this has been
        # freshly checked out.
        if not os.access(libtsk_path, os.R_OK):
            subprocess.check_call(["git", "submodule", "init"])
            subprocess.check_call(["git", "submodule", "update"])

        sdist.run(self)


class UpdateCommand(Command):
    """Update sleuthkit source.

    This is normally only run by packagers to make a new release.
    """
    version = time.strftime("%Y%m%d")

    timezone_minutes, _ = divmod(time.timezone, 60)
    timezone_hours, timezone_minutes = divmod(timezone_minutes, 60)

    # If timezone_hours is -1 %02d will format as -1 instead of -01
    # hence we detect the sign and force a leading zero.
    if timezone_hours < 0:
      timezone_string = '-%02d%02d' % (-timezone_hours, timezone_minutes)
    else:
      timezone_string = '+%02d%02d' % (timezone_hours, timezone_minutes)

    version_pkg = '%s %s' % (
        time.strftime('%a, %d %b %Y %H:%M:%S'), timezone_string)

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    files = {
        "sleuthkit/configure.ac": [
            ("([a-z_/]+)/Makefile",
             lambda m: m.group(0) if m.group(1).startswith("tsk") else "")
        ],

        "sleuthkit/Makefile.am": [
            ("SUBDIRS = .+", "SUBDIRS = tsk"),
        ],
        "class_parser.py": [
            ('VERSION = "[^"]+"', 'VERSION = "%s"' % version)
        ],
        "dpkg/changelog": [
            (r"pytsk3 \([^\)]+\)", "pytsk3 (%s-1)" % version),
            ("(<[^>]+>).+", r"\1  %s" % version_pkg),
        ],

    }

    def patch_sleuthkit(self):
        for filename, rules in iter(self.files.items()):
            data = open(filename).read()
            for search, replace in rules:
                data = re.sub(search, replace, data)

            with open(filename, "w") as fd:
                fd.write(data)

        for patch_file in glob.glob(os.path.join("patches", "*.patch")):
            subprocess.check_call(["git", "apply", "-p0", patch_file])

    def run(self):
        subprocess.check_call(["git", "stash"], cwd="sleuthkit")

        subprocess.check_call(["git", "submodule", "init"])
        subprocess.check_call(["git", "submodule", "update"])

        print("Updating sleuthkit")
        subprocess.check_call(["git", "reset", "--hard"], cwd="sleuthkit")
        subprocess.check_call(["git", "clean", "-x", "-f", "-d"],
                              cwd="sleuthkit")
        subprocess.check_call(["git", "checkout", "master"], cwd="sleuthkit")
        subprocess.check_call(["git", "pull"], cwd="sleuthkit")
        subprocess.check_call(["git", "fetch", "--tags"], cwd="sleuthkit")
        subprocess.check_call(["git", "checkout", "tags/sleuthkit-4.4.0"],
                              cwd="sleuthkit")

        self.patch_sleuthkit()
        subprocess.check_call(["./bootstrap"], cwd="sleuthkit")

        # Now derive the version based on the date.
        with open("version.txt", "w") as fd:
            fd.write(self.version)

        libtsk_path = "sleuthkit/tsk"

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


class TestCommand(Command):
    """Command to run tests."""
    user_options = []

    def initialize_options(self):
        self._dir = os.getcwd()

    def finalize_options(self):
        pass

    def run(self):
        run_tests.RunTests(os.path.join(".", "tests"))


class ProjectBuilder(object):
    """Class to help build the project."""

    def __init__(self, project_config, argv):
        """Initializes a project builder object."""
        self._project_config = project_config
        self._argv = argv

        # The path to the "tsk" directory.
        self._libtsk_path = "sleuthkit/tsk"

        # paths under the tsk/ directory which contain files we need to compile.
        self._sub_library_names = "auto  base  docs  fs  hashdb  img vs".split()

        # The args for the extension builder.
        self.extension_args = dict(
            define_macros=[],
            include_dirs=["talloc", "sleuthkit/tsk", "sleuthkit", "."],
            library_dirs=[],
            libraries=[],
        )

        # The sources to build.
        self._source_files = ["class.c", "error.c", "tsk3.c",
                              "pytsk3.c", "talloc/talloc.c"]

        # Path to the top of the unpacked sleuthkit sources.
        self._sleuthkit_path = "sleuthkit"

    def build(self):
        """Build everything."""
        # Fetch all c and cpp files from the subdirs to compile.
        for library_name in self._sub_library_names:
            for extension in ["*.c", "*.cpp"]:
                self._source_files.extend(glob.glob(
                    os.path.join(self._libtsk_path, library_name, extension)
                ))

        ext_modules = [Extension("pytsk3", self._source_files,
                                 **self.extension_args)]

        setup(
            cmdclass=dict(
                build_ext=BuildExtCommand,
                bdist_rpm=BdistRPMCommand,
                sdist=SDistCommand,
                update=UpdateCommand,
                test=TestCommand,
            ),
            ext_modules=ext_modules,
            **self._project_config
        )


if __name__ == "__main__":
    ProjectBuilder(setup_args, sys.argv).build()
