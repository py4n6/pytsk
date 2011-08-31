#!/usr/bin/python

import images
import sys
import pytsk3
from optparse import OptionParser

parser = OptionParser()
parser.add_option("-f", "--fstype", default=None,
                  help="File system type (use '-f list' for supported types)")

parser.add_option("-o", "--offset", default=0, type="int",
                  help="Offset in the image (in bytes)")

parser.add_option("-t", "--type", default="raw",
                  help="Type of image. Currently supported options 'raw', "
                  "'ewf'")

(options, args) = parser.parse_args()


if not args:
  print "You must specify an image."
  sys.exit(-1)

img = images.SelectImage(options.type, args)

try:
  volume = pytsk3.Volume_Info(img)
  for part in volume:
    print part.addr, part.desc, "%ss(%s)" % (part.start, part.start * 512), part.len

except IOError, e:
  print ("Error %s: Maybe specify a different image type using "
         "the -t option?" % e)
