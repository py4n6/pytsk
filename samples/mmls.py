#!/usr/bin/python

import ewf
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


class MyImgInfo(pytsk3.Img_Info):
  """An image info class which uses ewf as a backing reader.

  All we really need to do to provide TSK with the ability to read image formats
  in over ride the methods below.
  """

  def __init__(self, *paths_to_ewf_files):
    self.fd = ewf.ewffile(*paths_to_ewf_files)
    # Make sure to call the original base constructor.
    pytsk3.Img_Info.__init__(self, "")

  def get_size(self):
    """This should return the size of the image."""
    return self.fd.size

  def read(self, off, length):
    """This method simply returns data from a particular offset."""
    self.fd.seek(off)
    return self.fd.read(length)

  def close(self):
    """Dispose of the underlying file like object."""
    self.fd.close()

if options.type == "raw":
  if len(args) > 1:
    print "Only one dd image is supported in raw mode."
    sys.exit(-1)

  img = pytsk3.Img_Info(args[0])

elif options.type == "ewf":
  # Instantiate out special image object
  img = MyImgInfo(*args)


try:
  volume = pytsk3.Volume_Info(img)
  for part in volume:
    print part.addr, part.desc, part.start, part.len

except IOError, e:
  print ("Error %s: Maybe specify a different image type using "
         "the -t option?" % e)
