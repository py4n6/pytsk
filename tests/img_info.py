#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Tests for Img_Info."""

import os
import unittest

import pytsk3

import test_lib


class TSKImgInfoTestCase(unittest.TestCase):
  """Img_Info test case."""

  def _testInitialize(self, img_info):
    """Test the initialize functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEquals(img_info, None)

  def _testGetSize(self, img_info):
    """Test the get size functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEquals(img_info, None)

    self.assertEquals(img_info.get_size(), self._file_size)

  def _testRead(self, img_info):
    """Test the read functionality.

    Args:
      img_info: the Img_Info object.
    """
    self.assertNotEquals(img_info, None)

    self.assertEquals(img_info.read(0x5800, 16), b'place,user,passw')
    self.assertEquals(img_info.read(0x7c00, 16), b'This is another ')

    # Conforming to the POSIX seek the offset can exceed the file size
    # but reading will result in no data being returned.
    self.assertEquals(img_info.read(0x19000, 16), b'')

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

    self.assertNotEquals(img_info, None)

    self.assertEquals(img_info.read(0x5800, 16), b'place,user,passw')
    self.assertEquals(img_info.read(0x7c00, 16), b'This is another ')

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
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
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
    img_info = test_lib.FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = test_lib.FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = test_lib.FileObjectImageInfo(
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
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
    self._testInitialize(img_info)
    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
    self._testGetSize(img_info)
    img_info.close()

  def testRead(self):
    """Test the read functionality."""
    img_info = test_lib.FileObjectImageInfo(self._file_object, self._file_size)
    self._testRead(img_info)
    img_info.close()


if __name__ == '__main__':
  unittest.main()
