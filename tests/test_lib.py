"""Shared test case."""

import os

import pytsk3


class FileObjectImageInfo(pytsk3.Img_Info):
  """Img_Info that uses a file-like object."""

  def __init__(
      self, file_object, file_size, image_type=pytsk3.TSK_IMG_TYPE_RAW):
    """Initializes the image object.

    Args:
      file_object: the file-like object (instance of io.FileIO).
      file_size: the file size.
      image_type: optional SleuthKit image type. The default is RAW
                  (pytsk3.TSK_IMG_TYPE_RAW).

    Raises:
      ValueError: if the file-like object is invalid.
    """
    if not file_object:
      raise ValueError(u'Missing file-like object.')

    # pytsk3.Img_Info does not let you set attributes after initialization.
    self._file_object = file_object
    self._file_size = file_size
    # Using the old parent class invocation style otherwise some versions
    # of pylint complain also setting type to RAW to make sure Img_Info
    # does not do detection.
    pytsk3.Img_Info.__init__(self, url='', type=image_type)

  # Note: that the following functions are part of the pytsk3.Img_Info object
  # interface.

  def close(self):
    """Closes the volume IO object."""
    self._file_object = None

  def read(self, offset, size):
    """Reads a byte string from the image object at the specified offset.

    Args:
      offset: offset where to start reading.
      size: number of bytes to read.

    Returns:
      A byte string containing the data read.
    """
    self._file_object.seek(offset, os.SEEK_SET)
    return self._file_object.read(size)

  def get_size(self):
    """Retrieves the size."""
    return self._file_size
