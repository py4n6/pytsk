#!/usr/bin/env python3
#
# Copyright 2010, Michael Cohen <scudette@gmail.com>.
# Copyright 2012, 2026, Joachim Metz <joachim.metz@gmail.com>.
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
"""Script to update source."""

import argparse
import re
import os
import shutil
import subprocess
import sys
import time

# Update PYTHONPATH.
sys.path.insert(0, ".")

import class_parser


class SourceUpdater:
    """Updates the source."""

    SLEUTHKIT_GIT_TAG = "4.15.0"

    def __init__(self, use_head=False, verbose=False):
        """Initializes the source updater.

        Args:
          use_head (bool): Value to indicate if git HEAD should be used instead of
              the predefined SleuthKit git tag (SLEUTHKIT_GIT_TAG).
          verbose (bool): Value to indicate if the class parser should produce verbose
              output.
        """
        super().__init__()
        self.patch_files = [
            f"sleuthkit-{self.SLEUTHKIT_GIT_TAG:s}-configure.ac",
            f"sleuthkit-{self.SLEUTHKIT_GIT_TAG:s}-Makefile.am",
        ]
        self.use_head = use_head
        self.verbose = verbose
        self.version = time.strftime("%Y%m%d")

    def _apply_patches(self):
        """Applies patches."""
        for patch_file in self.patch_files:
            patch_file = os.path.join("patches", patch_file)
            if not os.path.exists(patch_file):
                print(f"No such patch file: {patch_file:s}")
                continue

            print(f"Applying patch file: {patch_file:s}")
            subprocess.check_call(
                ["git", "apply", os.path.join("..", patch_file)], cwd="sleuthkit"
            )

    def _generate_module(self):
        """Generates the Python module (pytsk3.cpp)."""
        print("Generating pytsk3.cpp")

        header_files = [
            os.path.join("sleuthkit", "tsk", "libtsk.h"),
            os.path.join("sleuthkit", "tsk", "base", "tsk_base.h"),
            os.path.join("sleuthkit", "tsk", "fs", "tsk_fs.h"),
            os.path.join("sleuthkit", "tsk", "img", "tsk_img.h"),
            os.path.join("sleuthkit", "tsk", "vs", "tsk_vs.h"),
            "tsk3.h",
        ]
        if self.verbose:
            verbose = 1
        else:
            verbose = 0

        class_parser.FREE = "talloc_free"
        parser = class_parser.HeaderParser("pytsk3", verbose=verbose)
        parser.module.init_string = "tsk_init();"
        parser.parse_filenames(header_files)

        with open("pytsk3.cpp", "w") as file_object:
            parser.write(file_object)

    def _print_configure_summary(self, output):
        """Prints the configure summary."""
        print_line = False
        for line in output.split(b"\n"):
            line = line.rstrip()
            if line == b"configure:":
                print_line = True

            if print_line:
                print(line)

    def _remove_files(self):
        """Remove files."""
        files_to_remove = [
            os.path.join(
                "sleuthkit", "win32", "PostgreSQL_CRT", "win32", "msvcr120.dll"
            ),
            os.path.join(
                "sleuthkit", "win32", "PostgreSQL_CRT", "win64", "msvcr120.dll"
            ),
        ]
        for path in files_to_remove:
            print(f"Removing: {path:s}")
            os.remove(path)

    def _update_files(self):
        """Updates files."""
        dpkg_version = time.strftime("%a, %d %b %Y %H:%M:%S")

        timezone_minutes, _ = divmod(time.timezone, 60)
        timezone_hours, timezone_minutes = divmod(timezone_minutes, 60)

        # If timezone_hours is -1 %02d will format as -1 instead of -01
        # hence we detect the sign and force a leading zero.
        if timezone_hours < 0:
            timezone_string = "-%02d%02d" % (-timezone_hours, timezone_minutes)
        else:
            timezone_string = "+%02d%02d" % (timezone_hours, timezone_minutes)

        files = {
            "class_parser.py": [
                ('VERSION = "[^"]+"', f'VERSION = "{self.version:s}"'),
            ],
            "dpkg/changelog": [
                (r"pytsk3 \([^\)]+\)", f"pytsk3 ({self.version:s}-1)"),
                ("(<[^>]+>).+", f"\\1  {dpkg_version:s} {timezone_string:s}"),
            ],
            "pyproject.toml": [
                ('version = "[^"]+"', f'version = "{self.version:s}"'),
            ],
        }
        for filename, rules in files.items():
            filename = os.path.join(*filename.split("/"))

            with open(filename, "r") as file_object:
                data = file_object.read()

            for search, replace in rules:
                data = re.sub(search, replace, data)

            with open(filename, "w") as file_object:
                file_object.write(data)

    def run(self):
        """Updates the source."""
        subprocess.check_call(["git", "stash"], cwd="sleuthkit")

        subprocess.check_call(["git", "submodule", "init"])
        subprocess.check_call(["git", "submodule", "update"])

        if self.use_head:
            print("Updating SleuthKit from HEAD")
        else:
            print(f"Updating SleuthKit from tag: {self.SLEUTHKIT_GIT_TAG:s}")

        subprocess.check_call(["git", "reset", "--hard"], cwd="sleuthkit")
        subprocess.check_call(["git", "clean", "-x", "-f", "-d"], cwd="sleuthkit")
        subprocess.check_call(["git", "checkout", "main"], cwd="sleuthkit")
        subprocess.check_call(["git", "pull"], cwd="sleuthkit")

        if not self.use_head:
            subprocess.check_call(
                ["git", "fetch", "--force", "--tags"], cwd="sleuthkit"
            )
            subprocess.check_call(
                ["git", "checkout", f"tags/sleuthkit-{self.SLEUTHKIT_GIT_TAG:s}"],
                cwd="sleuthkit",
            )
            self._apply_patches()

        if sys.platform == "win32":
            files_to_generate = [
                os.path.join("sleuthkit", "tsk", "tsk_config.h"),
            ]
            for path in files_to_generate:
                shutil.copy(f"{path:s}.in", path)

            path = os.path.join("sleuthkit", "tsk", "tsk_incs.h")
            with open(path, "w") as file_object:
                file_object.write(
                    "\n".join(
                        [
                            "#ifndef _TSK_INCS_H",
                            "#define _TSK_INCS_H",
                            "#include <unistd.h>",
                            "#ifndef __STDC_FORMAT_MACROS",
                            "#define __STDC_FORMAT_MACROS",
                            "#endif",
                            "#include <inttypes.h>",
                            "#include <sys/param.h>",
                            "#endif",
                            "",
                        ]
                    )
                )
        else:
            subprocess.check_call(["./bootstrap"], cwd="sleuthkit")

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

        self._remove_files()
        self._update_files()

        self._generate_module()


def Main():
    """The main program function.

    Returns:
      int: exit code that is provided to sys.exit().
    """
    argument_parser = argparse.ArgumentParser(description=("Updates the source."))

    argument_parser.add_argument(
        "--use-head",
        "--use_head",
        dest="use_head",
        action="store_true",
        default=False,
        help=(
            f"Use the latest version of Sleuthkit checked into git (HEAD) "
            f"instead of tag: {SourceUpdater.SLEUTHKIT_GIT_TAG:s}"
        ),
    )
    argument_parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help=("Verbose output"),
    )
    options = argument_parser.parse_args()

    updater = SourceUpdater(use_head=options.use_head, verbose=options.verbose)

    updater.run()

    return 0


if __name__ == "__main__":
    sys.exit(Main())
