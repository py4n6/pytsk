#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Tests for FS_Info."""

import os
import unittest

import pytsk3

import test_lib


# fls -l ./test_data/image.raw
# d/d 11:	lost+found	2012-05-25 17:55:50 (CEST)
#	2012-05-25 17:55:50 (CEST)	2012-05-25 17:55:50 (CEST)
#	0000-00-00 00:00:00 (UTC)	12288	0	0
# d/d 12:	a_directory	2012-05-25 17:59:23 (CEST)
#	2012-05-25 17:59:24 (CEST)	2012-05-25 17:59:23 (CEST)
#	0000-00-00 00:00:00 (UTC)	1024	5000	151107
# r/r 15:	passwords.txt	2012-05-25 18:00:53 (CEST)
#	2012-05-25 18:00:53 (CEST)	2012-05-25 18:01:03 (CEST)
#	0000-00-00 00:00:00 (UTC)	116	5000	151107
# r/- * 0:	passwords.txt~	0000-00-00 00:00:00 (UTC)
#	0000-00-00 00:00:00 (UTC)	0000-00-00 00:00:00 (UTC)
#	0000-00-00 00:00:00 (UTC)	0	0	0
# d/d 17:	$OrphanFiles	0000-00-00 00:00:00 (UTC)
#	0000-00-00 00:00:00 (UTC)	0000-00-00 00:00:00 (UTC)
#	0000-00-00 00:00:00 (UTC)	0	0	0


class TSKFsInfoTestCase(unittest.TestCase):
  """FS_Info test case."""

  def _testInitialize(self, fs_info):
    """Test the initialize functionality.

    Args:
      fs_info: the FS_Info object.
    """
    self.assertNotEquals(fs_info, None)

  def _testOpenMeta(self, fs_info):
    """Test the open meta functionality.

    Args:
      fs_info: the FS_Info object.
    """
    self.assertNotEquals(fs_info, None)

    file_object = fs_info.open_meta(15)

    self.assertNotEquals(file_object, None)

    with self.assertRaises(IOError):
      file_object = fs_info.open_meta(19)


class TSKFsInfoTest(TSKFsInfoTestCase):
  """FS_Info for testing."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._img_info = pytsk3.Img_Info(test_file)

  def testInitialize(self):
    """Test the initialize functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testInitialize(fs_info)

  def testOpenMeta(self):
    """Test the open meta functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testOpenMeta(fs_info)


class TSKFsInfoBogusTest(TSKFsInfoTestCase):
  """FS_Info for testing that fails."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'bogus.raw')
    self._img_info = pytsk3.Img_Info(test_file)

  def testInitialize(self):
    """Test the initialize functionality."""
    with self.assertRaises(IOError):
      pytsk3.FS_Info(self._img_info, offset=0)


class TSKFsInfoFileObjectTest(TSKFsInfoTestCase):
  """Tests the FS_Info object using an Img_Info file-like object."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')

    stat_info = os.stat(test_file)
    self._file_size = stat_info.st_size
    self._img_info = test_lib.FileObjectImageInfo(
        self._file_object, self._file_size)

  def testInitialize(self):
    """Test the initialize functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testInitialize(fs_info)

  def testOpenMeta(self):
    """Test the open meta functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testOpenMeta(fs_info)


class TSKFsInfoFileObjectWithDetectTest(TSKFsInfoTestCase):
  """Tests the FS_Info object with auto-detect Img_Info."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')

    stat_info = os.stat(test_file)
    self._file_size = stat_info.st_size
    self._img_info = test_lib.FileObjectImageInfo(
        self._file_object, self._file_size,
        image_type=pytsk3.TSK_IMG_TYPE_DETECT)

  def testInitialize(self):
    """Test the initialize functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testInitialize(fs_info)

  def testOpenMeta(self):
    """Test the open meta functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testOpenMeta(fs_info)


class TSKFsInfoFileObjectWithLargeSize(TSKFsInfoTestCase):
  """Tests the FS_Info object with a large size Img_Info."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    test_file = os.path.join('test_data', 'image.raw')
    self._file_object = open(test_file, 'rb')

    self._file_size = 1024 * 1024 * 1024 * 1024
    self._img_info = test_lib.FileObjectImageInfo(
        self._file_object, self._file_size)

  def testInitialize(self):
    """Test the initialize functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testInitialize(fs_info)

  def testOpenMeta(self):
    """Test the open meta functionality."""
    fs_info = pytsk3.FS_Info(self._img_info, offset=0)
    self._testOpenMeta(fs_info)


if __name__ == '__main__':
  unittest.main()
