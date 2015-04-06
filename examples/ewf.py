#!/usr/bin/python
#
# Copyright 2011, Michael Cohen <scudette@gmail.com>.
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
""" This is a module to interface to libewf.

This needs to be tested with the windows port.
"""
from ctypes import *
import ctypes.util

possible_names = ["libewf-1", "ewf",]
for name in possible_names:
  resolved = ctypes.util.find_library(name)
  if resolved:
    break

try:
  if resolved is None:
    raise ImportError("libewf not found")
  libewf = CDLL(resolved)
  if not libewf._name:
    raise OSError()
except OSError:
  raise ImportError("libewf not found")


class ewffile:
  """A file like object to provide access to the ewf file."""

  def __init__(self, *volumes):
    volume_array = c_char_p * len(volumes)
    self.handle = libewf.libewf_open(volume_array(*volumes),
                                     c_int(len(volumes)), c_int(1))
    if self.handle == 0:
      raise RuntimeError("Unable to open ewf file")

    self.readptr = 0
    size_p = pointer(c_ulonglong(0))
    libewf.libewf_get_media_size(self.handle, size_p)
    self.size = size_p.contents.value

  def seek(self, offset, whence=0):
    if whence == 0:
      self.readptr = offset
    elif whence == 1:
      self.readptr += offset
    elif whence == 2:
      self.readptr = self.size + offset

    self.readptr = min(self.readptr, self.size)

  def tell(self):
    return self.readptr

  def read(self, length):
    buf = create_string_buffer(length)
    length = libewf.libewf_read_random(
        self.handle, buf, c_ulong(length), c_ulonglong(self.readptr))

    return buf.raw[:length]

  def close(self):
    libewf.libewf_close(self.handle)

  def get_headers(self):
    properties = ["case_number", "description", "examinier_name",
                  "evidence_number", "notes", "acquiry_date",
                  "system_date", "acquiry_operating_system",
                  "acquiry_software_version", "password",
                  "compression_type", "model", "serial_number"]

    ## Make sure we parsed all headers
    libewf.libewf_parse_header_values(self.handle, c_int(4))
    result = {"size": self.size}
    buf = create_string_buffer(1024)
    for p in properties:
      libewf.libewf_get_header_value(self.handle, p, buf, 1024)
      result[p] = buf.value

    ## Get the hash
    if libewf.libewf_get_md5_hash(self.handle, buf, 16) == 1:
      result["md5"] = buf.raw[:16]

    return result


def ewf_open(volumes):
  return ewffile(volumes)

if __name__== "__main__":
  fd = ewffile("pyflag_stdimage_0.5.e01")
  print fd.get_headers()
  fd.seek(0x8E4B88)
  print "%r" % fd.read(100)
