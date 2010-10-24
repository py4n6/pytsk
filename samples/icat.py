#!/usr/bin/python

import pytsk3
from optparse import OptionParser
import sys
import pdb

parser = OptionParser()
parser.add_option("-f", "--fstype", default=None,
                  help="File system type (use '-f list' for supported types)")

(options, args) = parser.parse_args()

def error(string):
    print string
    sys.exit(1)

try:
    url = args[0]
except IndexError:
    error("You must specify an image (try '%s -h' for help)" % sys.argv[0])

if len(args)==2:
    inode = int(args[1])
else:
    error("You must have exactly two arguements provided")

## Now open and read the file specified

## Step 1: get an IMG_INFO object (url can be any URL that AFF4 can
## handle)
img = pytsk3.Img_Info(url)

## Step 2: Open the filesystem
fs = pytsk3.FS_Info(img)

## Step 3: Open the file using the inode
f = fs.open_meta(inode = inode)

## Step 4: Read all the data and print to stdout
offset = 0
size = f.info.meta.size
BUFF_SIZE = 1024 * 1024

while offset < size:
    available_to_read = min(BUFF_SIZE, size - offset)
    data = f.read_random(offset, available_to_read)
    if not data: break

    offset += len(data)
    print data
