#!/usr/bin/python2.6

import pytsk3
import stat
from errno import *
import pdb
import os, sys, re

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

VOLUMES =[]

int_re = re.compile("^(\d+)([kKmMgGs]?)$")
def parse_int(string):
    """ Parses an integer from a string. Supports suffixes """
    try:
        m = int_re.match(string)
    except TypeError:
        return int(string)

    if not m: raise ValueError("%r is not an integer" % string)

    base = int(m.group(1))
    suffix = m.group(2).lower()

    if not suffix:
        return base

    if suffix == 's':
        return base * 512

    if suffix == 'k':
        return base * 1024

    if suffix == 'm':
        return base * 1024 * 1024

    if suffix == 'g':
        return base * 1024 * 1024 * 1024

    raise ValueError("Unknown suffix '%r'" % suffix)

## A stub to allow for overriding later
Img_Info = pytsk3.Img_Info

def make_stat(meta):
    """ Return a stat structure from TSK metadata struct """
    meta_type_dispatcher = {
        pytsk3.TSK_FS_META_TYPE_DIR: stat.S_IFDIR,
        pytsk3.TSK_FS_META_TYPE_REG: stat.S_IFREG,
        pytsk3.TSK_FS_META_TYPE_FIFO: stat.S_IFIFO,
        pytsk3.TSK_FS_META_TYPE_CHR: stat.S_IFCHR,
        pytsk3.TSK_FS_META_TYPE_LNK: stat.S_IFLNK,
        pytsk3.TSK_FS_META_TYPE_BLK: stat.S_IFBLK,
        }

    s = fuse.Stat()
    s.st_ino = meta.addr
    s.st_dev = 0
    s.st_nlink = meta.nlink
    s.st_uid = meta.uid
    s.st_gid = meta.gid
    s.st_size = meta.size
    s.st_atime = meta.atime
    s.st_mtime = meta.mtime
    s.st_ctime = meta.crtime
    s.st_blocks = 2
    s.st_rdev = 0
    s.st_mode = meta_type_dispatcher.get(int(meta.type), 0)
    s.st_mode |= int(meta.mode)

    return s

class TSKFuse(Fuse):
    """ A class that makes a filesystem appear in a fuse
    filesystem. This is kind of like mounting it, but it uses the
    sleuthkit.
    """
    offset = '0'

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.root = '/'

    def main(self):
        self.offset = parse_int(self.offset)
        args = self.cmdline[1]
        if len(args) != 1:
            raise RuntimeError( "You must specify a single image name to load - try -h for help ")

        print "Opening filesystem in %s" % args[0]
        self.img = Img_Info(args[0])
        self.fs = pytsk3.FS_Info(self.img, offset = self.offset)

        ## Prepare the file class - this will be used to read specific
        ## files:
        self.file_class = self.TSKFuseFile
        self.file_class.fs = self.fs

        return Fuse.main(self)

    def getattr(self, path):
        try:
            f = self.fs.open(path)
        except RuntimeError: return None

        s = make_stat(f.info.meta)
        s.st_blksize = self.fs.info.block_size

        return s

    def readdir(self, path, offset):
        for f in self.fs.open_dir(path):
            try:
                result = fuse.Direntry(f.info.name.name)
                if f.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                    result.type = stat.S_IFDIR
                else:
                    result.type = stat.S_IFREG
            except AttributeError: pass

            yield result

    def unlink(self, path):
        pass

    def rmdir(self, path):
        pass

    def symlink(self, path, path1):
        pass

    def rename(self, path, path1):
        pass

    def link(self, path, path1):
        pass

    def chmod(self, path, mode):
        pass

    def chown(self, path, user, group):
        pass

    def truncate(self, path, len):
        pass

    def mknod(self, path, mode, dev):
        pass

    def mkdir(self, path, mode):
        pass

    def utime(self, path, times):
        pass

    def access(self, path, mode):
        pass

    def statfs(self):
        """
        Should return an object with statvfs attributes (f_bsize, f_frsize...).
        Eg., the return value of os.statvfs() is such a thing (since py 2.2).
        If you are not reusing an existing statvfs object, start with
        fuse.StatVFS(), and define the attributes.

        To provide usable information (ie., you want sensible df(1)
        output, you are suggested to specify the following attributes:

            - f_bsize - preferred size of file blocks, in bytes
            - f_frsize - fundamental size of file blcoks, in bytes
                [if you have no idea, use the same as blocksize]
            - f_blocks - total number of blocks in the filesystem
            - f_bfree - number of free blocks
            - f_files - total number of file inodes
            - f_ffree - nunber of free file inodes
        """
        s=fuse.StatVfs()
        info = self.fs.info

        s.f_bsize = info.dev_bsize
        s.f_frsize = 0
        s.f_blocks = info.block_count
        s.f_bfree = 0
        s.f_files = info.inum_count
        s.f_ffree = 0

        return s

    def fsinit(self):
        pass


    class TSKFuseFile(object):
        """ This is a file created on the AFF4 universe """
        direct_io = False
        keep_cache = True

        def __init__(self, path, flags, *mode):
            self.path = path
            try:
                self.fd = self.fs.open(path = path)
            except RuntimeError:
                raise IOError("unable to open %s" % path)

        def read(self, length, offset):
            return self.fd.read_random(offset, length)

        def _fflush(self):
            pass

        def fsync(self, isfsyncfile):
            pass

        def flush(self):
            pass

        def fgetattr(self):
            s = make_stat(self.fd.info.meta)
            s.st_blksize = self.fs.info.block_size

            return s

        def ftruncate(self, len):
            pass

        def write(self, *args, **kwargs):
            return -EOPNOTSUPP

        def lock(self, cmd, owner, **kw):
            return -EOPNOTSUPP

        def close(self):
            self.fd.close()


def main():
    global server
    usage = """
Userspace tsk-fuse: mount a filesystem through fuse.

%prog [options] image_name mount_point
"""

    server = TSKFuse(version="%prog " + fuse.__version__,
                     usage=usage,
                     dash_s_do='setsingle')

    # Disable multithreading: if you want to use it, protect all method of
    # XmlFile class with locks, in order to prevent race conditions
    server.multithreaded = False

    server.parser.add_option(mountopt="root", metavar="PATH", default='/',
                             help="mirror filesystem from under PATH [default: %default]")

    server.parser.add_option(mountopt="offset", metavar="INT", default=0,
                             help="Offset of filesystem [default: %default]")

    server.parser.add_option(mountopt="load", metavar="FILE,FILE,FILE", default=[],
                             help="Load these AFF4 volumes to populate the filesystem")

    server.parse(values = server, errex=1)

    ## Try to fix up the mount point if it was given relative to the
    ## CWD
    if server.fuse_args.mountpoint and not os.access(os.path.join("/",server.fuse_args.mountpoint), os.W_OK):
        server.fuse_args.mountpoint = os.path.join(os.getcwd(), server.fuse_args.mountpoint)

    ## Load the filesystem
    try:
        if server.fuse_args.mount_expected():
            os.chdir(server.root)
    except OSError:
        print >> sys.stderr, "can't enter root of underlying filesystem"
        sys.exit(1)

    server.main()

if __name__ == '__main__':
    main()
