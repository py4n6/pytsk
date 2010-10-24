#!/usr/bin/python

import pytsk3
from optparse import OptionParser
import sys
import pdb
import time
from pytsk3 import *
import gc

parser = OptionParser()
parser.add_option("-f", "--fstype", default=None,
                  help="File system type (use '-f list' for supported types)")

parser.add_option('-o', '--offset', default=0, type='int',
                  help='Offset in the image (in bytes)')

parser.add_option("-l", "--long", action='store_true', default=False,
                  help="Display long version (like ls -l)")

parser.add_option("-r", "--recursive", action='store_true', default=False,
                  help="Display a recursive file listing.")

(options, args) = parser.parse_args()

def error(string):
    print string
    sys.exit(1)

try:
    url = args[0]
except IndexError:
    error("You must specify an image (try '%s -h' for help)" % sys.argv[0])

if len(args)==1:
    inode = 0
    path = '/'
elif len(args)==2:
    try:
        inode = int(args[1])
        path = None
    except:
        inode = 0
        path = args[1]

else:
    error("Too many arguements provided")

FILE_TYPE_LOOKUP = {
    TSK_FS_NAME_TYPE_UNDEF : '-',
    TSK_FS_NAME_TYPE_FIFO : 'p',
    TSK_FS_NAME_TYPE_CHR : 'c',
    TSK_FS_NAME_TYPE_DIR : 'd',
    TSK_FS_NAME_TYPE_BLK : 'b',
    TSK_FS_NAME_TYPE_REG : 'r',
    TSK_FS_NAME_TYPE_LNK : 'l',
    TSK_FS_NAME_TYPE_SOCK : 'h',
    TSK_FS_NAME_TYPE_SHAD : 's',
    TSK_FS_NAME_TYPE_WHT : 'w',
    TSK_FS_NAME_TYPE_VIRT : 'v'
}

META_TYPE_LOOKUP = {
    TSK_FS_META_TYPE_REG : 'r',
    TSK_FS_META_TYPE_DIR : 'd',
    TSK_FS_META_TYPE_FIFO : 'p',
    TSK_FS_META_TYPE_CHR : 'c',
    TSK_FS_META_TYPE_BLK : 'b',
    TSK_FS_META_TYPE_LNK : 'h',
    TSK_FS_META_TYPE_SHAD : 's',
    TSK_FS_META_TYPE_SOCK :'s',
    TSK_FS_META_TYPE_WHT : 'w',
    TSK_FS_META_TYPE_VIRT : 'v'
}

NTFS_TYPES_TO_PRINT = [
    TSK_FS_ATTR_TYPE_NTFS_IDXROOT,
    TSK_FS_ATTR_TYPE_NTFS_DATA,
    TSK_FS_ATTR_TYPE_DEFAULT,
]

def print_inode(f, prefix=''):
    meta = f.info.meta
    name = f.info.name

    name_type = '-'
    if name:
        name_type = FILE_TYPE_LOOKUP.get(int(name.type), '-')

    meta_type = '-'
    if meta:
        meta_type = META_TYPE_LOOKUP.get(int(meta.type), '-')

    type = "%s/%s" % (name_type, meta_type)

    for attr in f:
        inode_type = int(attr.info.type)
        if inode_type in NTFS_TYPES_TO_PRINT:
            inode = "%s-%s-%s" % (meta.addr, int(attr.info.type), attr.info.id)

            attribute_name = attr.info.name
            if attribute_name and attribute_name != "$Data" and attribute_name != "$I30":
                filename = "%s:%s" % (name.name, attr.info.name)
            else:
                filename = name.name

            if filename == '.' or filename=='..': continue

            if meta and name:
                print "%s%s %s:\t%s" % (prefix, type, inode, filename)

## Now list the actual files (any of these can raise for any reason)


## Try to use AFF4 if its present
try:
    import pyaff4

    oracle = pyaff4.Resolver()

    class AFF4ImgInfo(pytsk3.Img_Info):
        def __init__(self, url):
            self.fd = oracle.open(
                pyaff4.RDFURN(url), 'r')
            if not self.fd:
                raise IOError("Unable to open %s" % url)
            pytsk3.Img_Info.__init__(self, '')

        def get_size(self):
            return self.fd.size.value

        def read(self, off, length):
            self.fd.seek(off)
            return self.fd.read(length)

        def close(self):
            self.fd.close()

    ## Step 1: get an IMG_INFO object (url can be any URL that AFF4 can
    ## handle)
    img = AFF4ImgInfo(url)
except ImportError:
    img = pytsk3.Img_Info(url)

## Step 2: Open the filesystem
fs = pytsk3.FS_Info(img, offset=options.offset)

## Step 3: Open the directory node
if path:
    directory = fs.open_dir(path=path)
else:
    directory = fs.open_dir(inode=inode)

## Step 4: Iterate over all files in the directory and print their
## name. What you get in each iteration is a proxy object for the
## TSK_FS_FILE struct - you can further dereference this struct into a
## TSK_FS_NAME and TSK_FS_META structs.
count = 0
def list_directory(directory, stack=None):
    stack.append(directory.info.fs_file.meta.addr)

    for f in directory:
        prefix = '+' * (len(stack) -1)
        if prefix: prefix += ' '
        print_inode(f, prefix)

        if options.recursive:
            try:
                dir = f.as_directory()

                inode = f.info.meta.addr
                ## This ensures that we dont recurse into a directory
                ## above the current level to avoid circular loops:
                if inode not in stack:
                    list_directory(dir, stack)

            except RuntimeError: pass

    stack.pop(-1)

list_directory(directory, [])

del fs
