#!/usr/bin/env python3
"""Tests for Img_Info."""

import os
import threading
import unittest

import pytsk3


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
    """Initializes the image object."""
    if not file_object:
      raise ValueError(u'Missing file-like object.')

    self._file_object = file_object
    self._file_size = file_size
    self._read_lock = threading.Lock()
    pytsk3.Img_Info.__init__(self, url='', type=image_type)

  def close(self):
    """Closes the volume IO object."""
    with self._read_lock:
      self._file_object = None

  def read(self, offset, size):
    """Reads a byte string from the image object at the specified offset."""
    with self._read_lock:
      file_object = self._file_object
      if file_object is None:
        return b''
      file_object.seek(offset, os.SEEK_SET)
      return file_object.read(size)

  def get_size(self):
    """Retrieves the size."""
    return self._file_size


class TSKImgInfoTestCase(unittest.TestCase):
  """Img_Info test case."""

  def _testInitialize(self, img_info):
    """Test the initialize functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEqual(img_info, None)

  def _testGetSize(self, img_info):
    """Test the get size functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEqual(img_info, None)

    self.assertEqual(img_info.get_size(), self._file_size)

  def _testRead(self, img_info):
    """Test the read functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEqual(img_info, None)

    self.assertEqual(img_info.read(0x5800, 16), b'place,user,passw')
    self.assertEqual(img_info.read(0x7c00, 16), b'This is another ')

    # Conforming to the POSIX seek the offset can exceed the file size
    # but reading will result in no data being returned.
    self.assertEqual(img_info.read(0x19000, 16), b'')

    with self.assertRaises(IOError):
      img_info.read(-1, 16)


class TSKImgInfoTest(TSKImgInfoTestCase):
  """The unit test for the Img_Info object."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    self._test_file = os.path.join('test_data', 'image.raw')
    self._file_size = 102400

  def testInitialize(self):
    """Test the initialize functionality."""
    img_info = pytsk3.Img_Info(url=self._test_file)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = pytsk3.Img_Info(url=self._test_file)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = pytsk3.Img_Info(url=self._test_file)

    self.assertNotEqual(img_info, None)

    self.assertEqual(img_info.read(0x5800, 16), b'place,user,passw')
    self.assertEqual(img_info.read(0x7c00, 16), b'This is another ')

    # Conforming to the POSIX seek the offset can exceed the file size
    # but reading will result in no data being returned. Note that the SleuthKit
    # does not conform to the posix standard and will raise and IO error.
    with self.assertRaises(IOError):
      img_info.read(0x19000, 16)

    with self.assertRaises(IOError):
      img_info.read(-1, 16)

    img_info.close()


class TSKImgInfoFileObjectTest(TSKImgInfoTestCase):
  """The unit test for the Img_Info object using a file-like object."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')

    stat_info = os.stat(test_file)
    self._file_size = stat_info.st_size

  def testInitialize(self):
    """Test the initialize functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testRead(img_info)
    img_info.close()


class TSKImgInfoFileObjectWithDetectTest(TSKImgInfoTestCase):
  """The unit test for the Img_Info object using a file-like object
     with image type: pytsk3.TSK_IMG_TYPE_DETECT."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')

    stat_info = os.stat(test_file)
    self._file_size = stat_info.st_size

  def testInitialize(self):
    """Test the initialize functionality."""
    img_info = FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)
    self._testRead(img_info)
    img_info.close()


class TSKImgInfoFileObjectLargeSizeTest(TSKImgInfoTestCase):
  """The unit test for the Img_Info object using a file-like object
     with a large size."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')
    self._file_size = 1024 * 1024 * 1024 * 1024

  def testInitialize(self):
    """Test the initialize functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)
    self._testRead(img_info)
    img_info.close()


if __name__ == '__main__':
  unittest.main()
