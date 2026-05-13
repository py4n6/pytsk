#!/usr/bin/env python3
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
import subprocess
import sys

from setuptools import Extension
from setuptools._distutils.ccompiler import new_compiler
from setuptools.command.build_ext import build_ext

from distutils import log
from distutils.dep_util import newer_group


class custom_build_ext(build_ext):
    """Custom build_ext command."""

    def _get_define_macros(self, compiler_type):
        """Determine the define macros.

        Args:
          compiler_type (str): compiler type.
        """
        if compiler_type == "msvc":
            return [
                ("WIN32", "1"),
                ("UNICODE", "1"),
                ("NOMINMAX", "1"),
                ("_CRT_SECURE_NO_WARNINGS", "1"),
            ]

        return [("HAVE_CONFIG_H", "1"), ("LOCALEDIR", '"/usr/share/locale"')]

    def _get_extra_compile_args(self, compiler_type):
        """Determine the extra compile arguments."""
        if compiler_type == "msvc":
            arguments = ["/EHsc"]
        else:
            arguments = ["-std=c++14"]

        if compiler_type == "mingw32":
            # Statically link libgcc and libstdc++
            arguments.extend(["-static-libgcc", "-static-libstdc++"])

        return arguments

    def _get_include_directories(self):
        """Determine the include directories."""
        return [
            ".",
            "talloc",
            os.path.join("sleuthkit"),
        ]

    def _get_libraries(self, compiler_type):
        """Determine the libraries."""
        if compiler_type == "msvc":
            return []

        return ["stdc++"]

    def _get_sources(self):
        """Determine the sources."""
        sources = [
            "class.cpp",
            "error.cpp",
            "tsk3.cpp",
            "pytsk3.cpp",
            os.path.join("talloc", "talloc.c"),
            os.path.join("sleuthkit", "tsk", "auto", "guid.cpp"),
        ]
        for path in ("base", "docs", "fs", "img", "pool", "util", "vs"):
            for extension in ("*.c", "*.cpp"):
                sources.extend(
                    glob.glob(os.path.join("sleuthkit", "tsk", path, extension))
                )

        return sources

    def _print_configure_summary(self, output):
        """Prints the configure summary."""
        print_line = False
        for line in output.decode("utf8").split("\n"):
            line = line.rstrip()
            if line == "configure:":
                print_line = True

            if print_line:
                print(line)

    def initialize_options(self):
        """Initialize build options."""
        super().initialize_options()

        compiler = new_compiler(compiler=self.compiler)

        # ext_module can be defined multiple times. It is currently assumed that
        # this is due to the experimental nature of tool.setuptools.ext-modules
        # at this time. Hence ext_modules is redefined as a single extension.
        self.distribution.ext_modules = [
            Extension(
                "pytsk3",
                define_macros=self._get_define_macros(compiler.compiler_type),
                extra_compile_args=self._get_extra_compile_args(compiler.compiler_type),
                include_dirs=self._get_include_directories(),
                libraries=self._get_libraries(compiler.compiler_type),
                sources=self._get_sources(),
            )
        ]

    def run(self):
        if not os.access("pytsk3.cpp", os.R_OK):
            raise OSError("Missing pytsk3.cpp")

        compiler = new_compiler(compiler=self.compiler)
        if compiler.compiler_type != "msvc":
            # We want to build as much as possible self contained Python binding.
            command = [
                "sh",
                "configure",
                "--disable-java",
                "--disable-multithreading",
                "--without-afflib",
                "--without-libbfio",
                "--without-libewf",
                "--without-libvhdi",
                "--without-libvmdk",
                "--without-libvslvm",
                "--without-zlib",
            ]
            output = subprocess.check_output(command, cwd="sleuthkit")
            self._print_configure_summary(output)

        super().run()
