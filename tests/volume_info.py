#!/usr/bin/env python3
"""Tests for Volume_Info."""

import os
import unittest

import pytsk3

import test_lib

# mmls ../test_data/tsk_volume_system.raw
# DOS Partition Table
# Offset Sector: 0
# Units are in 512-byte sectors
#
#      Slot    Start        End          Length       Description
# 00:  Meta    0000000000   0000000000   0000000001   Primary Table (#0)
# 01:  -----   0000000000   0000000000   0000000001   Unallocated
# 02:  00:00   0000000001   0000000350   0000000350   Linux (0x83)
# 03:  Meta    0000000351   0000002879   0000002529   DOS Extended (0x05)
# 04:  Meta    0000000351   0000000351   0000000001   Extended Table (#1)
# 05:  -----   0000000351   0000000351   0000000001   Unallocated
# 06:  01:00   0000000352   0000002879   0000002528   Linux (0x83)


class TSKVolumeInfoTestCase(unittest.TestCase):
    """Volume_Info test case."""

    maxDiff = None

    def _testInitialize(self, volume_info):
        """Test the initialize functionality.

        Args:
          volume_info: the Volume_Info object.
        """
        self.assertNotEqual(volume_info, None)

    def _testIterate(self, volume_info):
        """Test the iterate functionality.

        Args:
          volume_info: the Volume_Info object.
        """
        self.assertNotEqual(volume_info, None)
        self.assertNotEqual(getattr(volume_info, "info", None), None)

        self.assertEqual(volume_info.info.vstype, pytsk3.TSK_VS_TYPE_DOS)

        parts = []

        for part in volume_info:
            part_string = ("{0:02d}:  {1:010d}   {2:010d}   {3:010d}   {4:s}\n").format(
                part.addr,
                part.start,
                part.start + part.len - 1,
                part.len,
                part.desc.decode("utf-8"),
            )
            parts.append(part_string)

        self.assertEqual(len(parts), 7)

        expected_parts_string = (
            "00:  0000000000   0000000000   0000000001   Primary Table (#0)\n"
            "01:  0000000000   0000000000   0000000001   Unallocated\n"
            "02:  0000000001   0000000350   0000000350   Linux (0x83)\n"
            "03:  0000000351   0000002879   0000002529   DOS Extended (0x05)\n"
            "04:  0000000351   0000000351   0000000001   Extended Table (#1)\n"
            "05:  0000000351   0000000351   0000000001   Unallocated\n"
            "06:  0000000352   0000002879   0000002528   Linux (0x83)\n"
        )

        self.assertEqual("".join(parts), expected_parts_string)


class TSKVolumeInfoTest(TSKVolumeInfoTestCase):
    """Volume_Info for testing."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "tsk_volume_system.raw")
        self._img_info = pytsk3.Img_Info(test_file)

    def testInitialize(self):
        """Test the initialize functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testInitialize(volume_info)

    def testIterate(self):
        """Test the iterate functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testIterate(volume_info)

    def testMountAllocatedPartitions(self):
        """Volume_Info → FS_Info(offset=part.start*512) → list root.

        Mirrors dfirwizard / imagemounter / GRR. Exercises partition
        offset arithmetic and clean OSError propagation when a partition
        is too small to mount.
        """
        volume_info = pytsk3.Volume_Info(self._img_info)
        allocated = [p for p in volume_info if p.flags & pytsk3.TSK_VS_PART_FLAG_ALLOC]
        self.assertGreater(len(allocated), 0)
        mounted = 0
        for part in allocated:
            try:
                fs_info = pytsk3.FS_Info(self._img_info, offset=part.start * 512)
            except (IOError, OSError):
                continue
            mounted += 1
            list(fs_info.open_dir("/"))
        self.assertGreater(mounted, 0)


class TSKVolumeInfoBogusTest(TSKVolumeInfoTestCase):
    """Volume_Info for testing that fails."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "bogus.raw")
        self._img_info = pytsk3.Img_Info(test_file)

    def testInitialize(self):
        """Test the initialize functionality."""
        with self.assertRaises(IOError):
            pytsk3.Volume_Info(self._img_info)


class TSKVolumeInfoFileObjectTest(TSKVolumeInfoTestCase):
    """Tests the Volume_Info object using an Img_Info file-like object."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "tsk_volume_system.raw")
        self._file_object = open(test_file, "rb")

        stat_info = os.stat(test_file)
        self._file_size = stat_info.st_size
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size
        )

    def testInitialize(self):
        """Test the initialize functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testInitialize(volume_info)

    def testIterate(self):
        """Test the iterate functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testIterate(volume_info)


class TSKVolumeInfoFileObjectWithDetectTest(TSKVolumeInfoTestCase):
    """Tests the Volume_Info object with auto-detect Img_Info."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "tsk_volume_system.raw")
        self._file_object = open(test_file, "rb")

        stat_info = os.stat(test_file)
        self._file_size = stat_info.st_size
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size, image_type=pytsk3.TSK_IMG_TYPE_DETECT
        )

    def testInitialize(self):
        """Test the initialize functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testInitialize(volume_info)

    def testIterate(self):
        """Test the iterate functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testIterate(volume_info)


class TSKVolumeInfoFileObjectWithLargeSize(TSKVolumeInfoTestCase):
    """Tests the Volume_Info object with a large size Img_Info."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "tsk_volume_system.raw")
        self._file_object = open(test_file, "rb")

        self._file_size = 1024 * 1024 * 1024 * 1024
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size
        )

    def testInitialize(self):
        """Test the initialize functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)
        self._testInitialize(volume_info)

    def testIterate(self):
        """Test the iterate functionality."""
        volume_info = pytsk3.Volume_Info(self._img_info)

        self.assertNotEqual(volume_info, None)
        self.assertNotEqual(getattr(volume_info, "info", None), None)

        self.assertEqual(volume_info.info.vstype, pytsk3.TSK_VS_TYPE_DOS)

        parts = []

        for part in volume_info:
            part_string = ("{0:02d}:  {1:010d}   {2:010d}   {3:010d}   {4:s}\n").format(
                part.addr,
                part.start,
                part.start + part.len - 1,
                part.len,
                part.desc.decode("utf-8"),
            )
            parts.append(part_string)

        # Note that due to the size the SleuthKit will add a non-existing part:
        # 07:  0000002880   2147483647   2147480768   Unallocated

        self.assertEqual(len(parts), 8)

        expected_parts_string = (
            "00:  0000000000   0000000000   0000000001   Primary Table (#0)\n"
            "01:  0000000000   0000000000   0000000001   Unallocated\n"
            "02:  0000000001   0000000350   0000000350   Linux (0x83)\n"
            "03:  0000000351   0000002879   0000002529   DOS Extended (0x05)\n"
            "04:  0000000351   0000000351   0000000001   Extended Table (#1)\n"
            "05:  0000000351   0000000351   0000000001   Unallocated\n"
            "06:  0000000352   0000002879   0000002528   Linux (0x83)\n"
            "07:  0000002880   2147483647   2147480768   Unallocated\n"
        )

        self.assertEqual("".join(parts), expected_parts_string)


if __name__ == "__main__":
    unittest.main()
