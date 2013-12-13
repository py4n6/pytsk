#!/usr/bin/python
#
# Copyright 2013, Joachim Metz <joachim.metz@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import pytsk3
import unittest


class FileObjectImageInfo(pytsk3.Img_Info):
  """Class that implements a pytsk3 image object using a file-like object."""

  def __init__(self, file_object, file_size):
    """Initializes the image object.

    Args:
      file_object: the file-like object (instance of io.FileIO).
      file_size: the file size.

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
    pytsk3.Img_Info.__init__(self, '', pytsk3.TSK_IMG_TYPE_RAW)

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


class TSKImgInfoTest(unittest.TestCase):
  """The unit test for the Img_Info object."""

  def setUp(self):
    """Sets up the needed objects used throughout the test."""
    self._test_file = os.path.join('test_data', 'image.raw')

  def testInitialize(self):
    """Test the initialize functionality."""
    img_info = pytsk3.Img_Info(self._test_file)

    self.assertNotEquals(img_info, None)

    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = pytsk3.Img_Info(self._test_file)

    self.assertEquals(img_info.get_size(), 102400)

    img_info.close()

  def testRead(self):
    """Test the seek functionality."""
    img_info = pytsk3.Img_Info(self._test_file)

    self.assertEquals(img_info.read(0x5800, 16), 'place,user,passw')
    self.assertEquals(img_info.read(0x7c00, 16), 'This is another ')

    # Conforming to the POSIX seek the offset can exceed the file size
    # but reading will result in no data being returned. Note that the SleuthKit
    # does not conform to the posix standard and will raise and IO error.
    with self.assertRaises(IOError):
      img_info.read(0x19000, 16)

    with self.assertRaises(IOError):
      img_info.read(-1, 16)

    img_info.close()


class TSKImgInfoFileObjectTest(unittest.TestCase):
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

    self.assertNotEquals(img_info, None)

    img_info.close()

  def testGetSize(self):
    """Test the get size functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)

    self.assertEquals(img_info.get_size(), 102400)

    img_info.close()

  def testRead(self):
    """Test the seek functionality."""
    img_info = FileObjectImageInfo(self._file_object, self._file_size)

    self.assertEquals(img_info.read(0x5800, 16), 'place,user,passw')
    self.assertEquals(img_info.read(0x7c00, 16), 'This is another ')

    # Conforming to the POSIX seek the offset can exceed the file size
    # but reading will result in no data being returned.
    self.assertEquals(img_info.read(0x19000, 16), '')

    with self.assertRaises(IOError):
      img_info.read(-1, 16)

    img_info.close()


if __name__ == '__main__':
  unittest.main()
