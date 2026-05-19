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
"""Build back-end for pytsk."""

import glob
import os
import shlex
import subprocess

from setuptools import Extension
from setuptools import errors
from setuptools._distutils import log
from setuptools._distutils._modified import newer_group
from setuptools._distutils.ccompiler import new_compiler
from setuptools.command.build_ext import build_ext

# This file does not follow the naming convention specified in .pylintrc.
# pylint: disable=invalid-name


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

        return [
            ("HAVE_CONFIG_H", "1"),
            ("LOCALEDIR", '"/usr/share/locale"'),
            # Make libtsk's lock_t and per-thread error storage active in
            # pytsk3's own translation units so they match libtsk's. On
            # MSVC this is set automatically by tsk_os.h via _MSC_VER.
            ("TSK_MULTITHREAD_LIB", None),
        ]

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

        # pthread is needed because TSK_MULTITHREAD_LIB pulls in pthread_key_*
        # and pthread_mutex_* from tsk_error.c and tsk_lock.c. Harmless on
        # glibc 2.34+ (folded into libc) and macOS (libSystem stub).
        return ["stdc++", "pthread"]

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
        for line in output.split("\n"):
            line = line.rstrip()
            if line == "configure:":
                print_line = True

            if print_line:
                print(line)

    def _run_shell_command(self, command):
        """Runs a command."""
        arguments = shlex.split(f"sh {command:s}")

        # pylint: disable=consider-using-with
        process = subprocess.Popen(
            arguments,
            cwd="sleuthkit",
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        if not process:
            raise RuntimeError(f"Running: {command:s} failed.")

        output, error = process.communicate()
        if process.returncode != 0:
            error = "\n".join(error.split("\n")[-5:])
            raise RuntimeError(f"Running: {command:s} failed with error:\n{error:s}.")

        return output

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
                include_dirs=self._get_include_directories(),
                libraries=self._get_libraries(compiler.compiler_type),
                sources=self._get_sources(),
            )
        ]

    # Override build_extension to not have clang on Mac OS fail with:
    # invalid argument '-std=c++14' not allowed with 'C'
    def build_extension(self, ext):
        """Builds the extension."""
        sources = ext.sources
        if sources is None or not isinstance(sources, (list, tuple)):
            raise errors.SetupError(
                f"in 'ext_modules' option (extension '{ext.name:s}'), 'sources' "
                f"must be present and must be a list of source filenames"
            )
        sources = sorted(sources)

        extension_path = self.get_ext_fullpath(ext.name)
        depends = ext.sources + ext.depends
        if not (self.force or newer_group(depends, extension_path, "newer")):
            log.debug("skipping '%s' extension (up-to-date)", ext.name)
            return

        log.info("building '%s' extension", ext.name)

        c_sources = []
        cxx_sources = []
        for source in ext.sources:
            if source.endswith(".c"):
                c_sources.append(source)
            else:
                cxx_sources.append(source)

        objects = []
        for lang, sources in (("c", c_sources), ("c++", cxx_sources)):
            extra_args = ext.extra_compile_args or []
            if lang == "c++":
                if self.compiler.compiler_type == "msvc":
                    extra_args.append("/EHsc")
                else:
                    extra_args.append("-std=c++14")

            macros = ext.define_macros[:]
            for undef in ext.undef_macros:
                macros.append((undef,))

            compiled_objects = self.compiler.compile(
                sources,
                output_dir=self.build_temp,
                macros=macros,
                include_dirs=ext.include_dirs,
                debug=self.debug,
                extra_postargs=extra_args,
                depends=ext.depends,
            )
            objects.extend(compiled_objects)

        # pylint: disable=attribute-defined-outside-init
        self._built_objects = objects[:]
        if ext.extra_objects:
            objects.extend(ext.extra_objects)

        extra_args = ext.extra_link_args or []
        # When MinGW32 is used statically link libgcc and libstdc++.
        if self.compiler.compiler_type == "mingw32":
            extra_args.extend(["-static-libgcc", "-static-libstdc++"])

        if ext.extra_objects:
            objects.extend(ext.extra_objects)
        extra_args = ext.extra_link_args or []

        language = ext.language or self.compiler.detect_language(sources)

        self.compiler.link_shared_object(
            objects,
            extension_path,
            libraries=self.get_libraries(ext),
            library_dirs=ext.library_dirs,
            runtime_library_dirs=ext.runtime_library_dirs,
            extra_postargs=extra_args,
            export_symbols=self.get_export_symbols(ext),
            debug=self.debug,
            build_temp=self.build_temp,
            target_lang=language,
        )

    def run(self):
        if not os.access("pytsk3.cpp", os.R_OK):
            raise OSError("Missing pytsk3.cpp")

        compiler = new_compiler(compiler=self.compiler)
        if compiler.compiler_type != "msvc":
            # We want to build as much as possible self contained Python binding.
            output = self._run_shell_command(
                " ".join(
                    [
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
                )
            )
            self._print_configure_summary(output)

        super().run()
