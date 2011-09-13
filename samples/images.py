"""This module selects a suitable image info object based on the type."""
import bisect
import ewf
import pytsk3
import sys


class EWFImgInfo(pytsk3.Img_Info):
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


class SplitImage(pytsk3.Img_Info):
  """Virtualize access to split images.

  Note that unlike other tools (e.g. affuse) we do not assume that the images
  are the same size.
  """

  def __init__(self, *files):
    self.fds = []
    self.offsets = [0]
    offset = 0

    for fd in files:
      # Support either a filename or file like objects
      if not hasattr(fd, "read"):
        fd = open(fd, "rb")

      fd.seek(0,2)

      offset += fd.tell()
      self.offsets.append(offset)
      self.fds.append(fd)

    self.size = offset

    # Make sure to call the original base constructor.
    pytsk3.Img_Info.__init__(self, "")

  def get_size(self):
    return self.size

  def read(self, offset, length):
    """Read a buffer from the split image set.

    Handles the buffer straddling images.
    """
    result = ""

    # The total available size in the file
    length = int(length)
    length = min(length, long(self.size) - offset)

    while length > 0:
      data = self._ReadPartial(offset, length)
      if not data: break

      length -= len(data)
      result += data
      offset += len(data)

    return result

  def _ReadPartial(self, offset, length):
    """Read as much as we can from the current image."""
    # The part we need to read from.
    idx = bisect.bisect_right(self.offsets, offset + 1) - 1
    fd = self.fds[idx]

    # The offset this part is in the overall image
    img_offset = self.offsets[idx]
    fd.seek(offset - img_offset)

    # This can return less than length
    return fd.read(length)


def SelectImage(img_type, files):
  if img_type == "raw":
    if len(files) == 1:
      # For a single file this is faster.
      return pytsk3.Img_Info(files[0])
    else:
      return SplitImage(*files)

  elif img_type == "ewf":
    # Instantiate our special image object
    return EWFImgInfo(*files)
