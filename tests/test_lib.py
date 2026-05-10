"""Shared test case."""

import os
import threading

import pytsk3


def walk_filesystem(directory, prefix=b'', max_depth=8, _depth=0):
  """Recursive directory walk yielding (path, entry) pairs.

  Mirrors samples/fls.py and dfvfs's TSKFileSystem traversal: skip
  '.', '..', and the synthetic '$OrphanFiles' node; recurse via
  File.as_directory(); cap depth to avoid runaway loops on
  pathological inputs (e.g. cyclic symlinks).
  """
  if _depth > max_depth:
    return
  for entry in directory:
    if not entry.info or not entry.info.name:
      continue
    name = entry.info.name.name
    if name in (b'.', b'..', b'$OrphanFiles'):
      continue
    yield prefix + b'/' + name, entry
    meta = entry.info.meta
    if meta is not None and meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
      try:
        sub = entry.as_directory()
      except (IOError, OSError):
        continue
      yield from walk_filesystem(
          sub, prefix + b'/' + name, max_depth, _depth + 1)


class FileObjectImageInfo(pytsk3.Img_Info):
  """Img_Info that uses a file-like object.

  Thread-safety: pytsk3 may invoke read() concurrently from multiple
  threads (true under free-threaded Python; possible even with the
  GIL via cooperative thread switches across the seek+read pair).
  Most file-like objects implement read positioning as a stateful
  seek+read on a single fd, so concurrent calls would race. We
  serialize the seek/read pair under a per-instance lock so that
  pytsk3 callers can share one FileObjectImageInfo across threads.
  """

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
    # Guards the seek+read pair on _file_object. Created before the
    # parent __init__ because pytsk3 may begin proxying read() calls
    # as soon as the constructor returns from Python's perspective.
    self._read_lock = threading.Lock()
    # Using the old parent class invocation style otherwise some versions
    # of pylint complain also setting type to RAW to make sure Img_Info
    # does not do detection.
    pytsk3.Img_Info.__init__(self, url='', type=image_type)

  # Note: that the following functions are part of the pytsk3.Img_Info object
  # interface.

  def close(self):
    """Closes the volume IO object."""
    with self._read_lock:
      self._file_object = None

  def read(self, offset, size):
    """Reads a byte string from the image object at the specified offset.

    Args:
      offset: offset where to start reading.
      size: number of bytes to read.

    Returns:
      A byte string containing the data read.
    """
    with self._read_lock:
      file_object = self._file_object
      if file_object is None:
        return b''
      file_object.seek(offset, os.SEEK_SET)
      return file_object.read(size)

  def get_size(self):
    """Retrieves the size."""
    return self._file_size
