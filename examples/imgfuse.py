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
""" This is a fuse driver that makes an image mountable through the standard
linux loopback driver. This allows users to mount say an encase image directly
through the loopback driver.
"""

import images
import os,sys
from errno import *
import stat

import thread

# pull in some spaghetti to make this stuff work without fuse-py being installed
try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse

if not hasattr(fuse, '__version__'):
    raise RuntimeError, \
        "your fuse-py doesn't know of fuse.__version__, probably it's too old."

fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')

class Xmp(Fuse):
    def main(self):
      options, args = self.parser.parse_args()
      self.fd = images.SelectImage(options.type, args)

      return Fuse.main(self)

    def getattr(self, path):
      s = fuse.Stat()
      s.st_ino = 1
      s.st_dev = 0
      s.st_nlink = 1
      s.st_uid = 0
      s.st_gid = 0
      s.st_size = self.fd.get_size()
      s.st_atime = 0
      s.st_mtime = 0
      s.st_ctime = 0
      s.st_blocks = 20000
      s.st_rdev = 0
      s.st_mode = 33188
      if path.endswith('/'):
        s.st_mode = 16877

      return s

    def readlink(self, path):
        raise IOError("No symbolic links supported on forensic filesystem at %s" % path)

    def readdir(self, path, offset):
      # We make it look like there is a single image.raw file in this directory
      if path == "/":
        result = fuse.Direntry("image.raw")
        result.type = stat.S_IFREG

        yield result

    def unlink(self, path):
        raise IOError("Unable to modify Virtual Filesystem")

    def rmdir(self, path):
        raise IOError("Unable to modify Virtual Filesystem")

    def symlink(self, path, path1):
        raise IOError("Unable to modify Virtual Filesystem")

    def rename(self, path, path1):
        raise IOError("Unable to modify Virtual Filesystem")

    def link(self, path, path1):
        raise IOError("Unable to modify Virtual Filesystem")

    def chmod(self, path, mode):
        raise IOError("Unable to modify Virtual Filesystem")

    def chown(self, path, user, group):
        raise IOError("Unable to modify Virtual Filesystem")

    def truncate(self, path, size):
        raise IOError("Unable to modify Virtual Filesystem")

    def mknod(self, path, mode, dev):
        raise IOError("Unable to modify Virtual Filesystem")

    def mkdir(self, path, mode):
        raise IOError("Unable to modify Virtual Filesystem")

    def utime(self, path, times):
        raise IOError("Unable to modify Virtual Filesystem")

    def open(self, path, flags):
        """ For now we only support a single image in the same filesystem, so
        any open will simply open this one image """
        if path == "/image.raw":
        ## Image is already open
          return 0
        else:
          return EBADF

    def read(self, path, length, offset):
      result = self.fd.read(offset, length)

      return result

    def write(self, path, buf, off):
        ## We do not modify the data, but we need to pretend that we
        ## are so callers dont panic - this is handy when mounting
        ## ext3 filesystems over loopback, where the kernel really
        ## wants to update the journal and would freak if it can't.
        return len(buf)

    def release(self, path, flags):
        return 0

    def statfs(self):
        """
        Should return a tuple with the following 6 elements:
            - blocksize - size of file blocks, in bytes
            - totalblocks - total number of blocks in the filesystem
            - freeblocks - number of free blocks
            - totalfiles - total number of file inodes
            - freefiles - nunber of free file inodes

        Feel free to set any of the above values to 0, which tells
        the kernel that the info is not available.
        """
        blocks_size = 1024
        blocks = 100000
        blocks_free = 25000
        files = 100000
        files_free = 60000
        namelen = 80
        return (blocks_size, blocks, blocks_free, files, files_free, namelen)

    def fsync(self, path, isfsyncfile):
        return 0

if __name__ == '__main__':
    #Now we create a fuse object with that IO subsystem:
    server = Xmp()
    server.flags = 0
    server.multithreaded = False;

    server.parser.add_option("-t", "--type", default="raw",
                             help="Type of image. Currently supported options 'raw', "
                             "'ewf'")

    server.parse(values = server, errex=1)

    ## Try to fix up the mount point if it was given relative to the
    ## CWD
    if server.fuse_args.mountpoint and not os.access(os.path.join("/",server.fuse_args.mountpoint), os.W_OK):
        server.fuse_args.mountpoint = os.path.join(os.getcwd(), server.fuse_args.mountpoint)

    server.main()
