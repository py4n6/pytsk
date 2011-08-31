"""This module selects a suitable image info object based on the type."""

import ewf
import pytsk3
import sys


class MyImgInfo(pytsk3.Img_Info):
  """An image info class which uses ewf as a backing reader.

  All we really need to do to provide TSK with the ability to read image formats
  is override the methods below.
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


def SelectImage(img_type, files):
  if img_type == "raw":
    if len(files) > 1:
      print "Only one dd image is supported in raw mode."
      sys.exit(-1)

    return pytsk3.Img_Info(files[0])

  elif img_type == "ewf":
    # Instantiate our special image object
    return MyImgInfo(*files)
