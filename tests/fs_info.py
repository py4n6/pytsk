#!/usr/bin/env python3
"""Tests for FS_Info."""

import os
import unittest

import pytsk3

from tests import test_lib

# fls -l ./test_data/image.raw
# d/d 11:	lost+found	2012-05-25 17:55:50 (CEST)
# 	2012-05-25 17:55:50 (CEST)	2012-05-25 17:55:50 (CEST)
# 	0000-00-00 00:00:00 (UTC)	12288	0	0
# d/d 12:	a_directory	2012-05-25 17:59:23 (CEST)
# 	2012-05-25 17:59:24 (CEST)	2012-05-25 17:59:23 (CEST)
# 	0000-00-00 00:00:00 (UTC)	1024	5000	151107
# r/r 15:	passwords.txt	2012-05-25 18:00:53 (CEST)
# 	2012-05-25 18:00:53 (CEST)	2012-05-25 18:01:03 (CEST)
# 	0000-00-00 00:00:00 (UTC)	116	5000	151107
# r/- * 0:	passwords.txt~	0000-00-00 00:00:00 (UTC)
# 	0000-00-00 00:00:00 (UTC)	0000-00-00 00:00:00 (UTC)
# 	0000-00-00 00:00:00 (UTC)	0	0	0
# d/d 17:	$OrphanFiles	0000-00-00 00:00:00 (UTC)
# 	0000-00-00 00:00:00 (UTC)	0000-00-00 00:00:00 (UTC)
# 	0000-00-00 00:00:00 (UTC)	0	0	0


class TSKFsInfoTestCase(unittest.TestCase):
    """FS_Info test case."""

    def _testInitialize(self, fs_info):
        """Test the initialize functionality.

        Args:
          fs_info: the FS_Info object.
        """
        self.assertNotEqual(fs_info, None)

    def _testOpenMeta(self, fs_info):
        """Test the open meta functionality.

        Args:
          fs_info: the FS_Info object.
        """
        self.assertNotEqual(fs_info, None)

        file_object = fs_info.open_meta(15)

        self.assertNotEqual(file_object, None)

        with self.assertRaises(OSError):
            file_object = fs_info.open_meta(19)


class TSKFsInfoTest(TSKFsInfoTestCase):
    """FS_Info for testing."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "image.raw")
        self._img_info = pytsk3.Img_Info(test_file)

    def testInitialize(self):
        """Test the initialize functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testInitialize(fs_info)

    def testOpenMeta(self):
        """Test the open meta functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testOpenMeta(fs_info)

    def testReadAttributesByTypeId(self):
        """Read every file attribute by (type, id).

        GRR's sleuthkit.py reads NTFS ADS streams via
        `read_random(offset, size, attr.info.type, attr.info.id)`; the
        same shape works on ext for the default data attribute. Iterating
        a File's attributes was the most race-prone API pre-FT-fix.
        """
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        file_object = fs_info.open_meta(15)  # passwords.txt
        sizes = [
            len(
                file_object.read_random(
                    0, attribute.info.size, attribute.info.type, attribute.info.id
                )
            )
            for attribute in file_object
        ]
        self.assertIn(116, sizes)  # the passwords.txt data attribute

    def testChunkedReadMatchesWhole(self):
        """Streaming reads in small chunks must equal the whole-file read.

        dfvfs's tsk_file_io.py and dfirwizard both stream files this way;
        short chunks amplify any off-by-one in the snapshot/lock path.
        """
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        file_object = fs_info.open_meta(15)
        size = file_object.info.meta.size
        whole = file_object.read_random(0, size)
        chunks = []
        offset = 0
        while offset < size:
            chunk = file_object.read_random(offset, 16)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        self.assertEqual(b"".join(chunks), whole)


class TSKFsInfoBogusTest(TSKFsInfoTestCase):
    """FS_Info for testing that fails."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "bogus.raw")
        self._img_info = pytsk3.Img_Info(test_file)

    def testInitialize(self):
        """Test the initialize functionality."""
        with self.assertRaises(OSError):
            pytsk3.FS_Info(self._img_info, offset=0)


class TSKFsInfoFileObjectTest(TSKFsInfoTestCase):
    """Tests the FS_Info object using an Img_Info file-like object."""

    def _WalkFileSystem(self, directory, prefix=b"", max_depth=8, depth=0):
        """Recurses a directory and yields (path, entry) pairs.

        Skip '.', '..', and the synthetic '$OrphanFiles' node; recurse via
        File.as_directory(); cap depth to avoid runaway loops on pathological inputs,
        such as cyclic symlinks.
        """
        if depth <= max_depth:
            for entry in directory:
                if not entry.info or not entry.info.name:
                    continue

                name = entry.info.name.name
                if name in (b".", b"..", b"$OrphanFiles"):
                    continue

                path = prefix + b"/" + name
                yield path, entry

                meta = entry.info.meta
                if meta is not None and meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                    try:
                        sub_directory = entry.as_directory()
                    except OSError:
                        continue

                    path = prefix + b"/" + name
                    yield from self._WalkFileSystem(
                        sub_directory,
                        prefix=path,
                        max_depth=max_depth,
                        depth=depth + 1,
                    )

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "image.raw")

        # pylint: disable=consider-using-with
        self._file_object = open(test_file, "rb")

        stat_info = os.stat(test_file)
        self._file_size = stat_info.st_size
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size
        )

    def testInitialize(self):
        """Test the initialize functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testInitialize(fs_info)

    def testOpenMeta(self):
        """Test the open meta functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testOpenMeta(fs_info)

    def testRecursiveWalkMatchesAcrossOpenPaths(self):
        """Walk every file via a file-like object backed image.

        Tests proxied read callback, parent keepalive, and the open-by-inode versus
        open-by-path paths in a single walk.
        """
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        directory = fs_info.open_dir("/")

        paths = dict(self._WalkFileSystem(directory))
        self.assertIn(b"/passwords.txt", paths)
        self.assertIn(b"/a_directory/a_file", paths)

        for path, entry in paths.items():
            meta = entry.info.meta
            if meta is None or meta.type != pytsk3.TSK_FS_META_TYPE_REG:
                continue

            by_inode = fs_info.open_meta(meta.addr).read_random(0, meta.size)
            by_path = fs_info.open(path.decode("utf-8")).read_random(0, meta.size)
            self.assertEqual(by_inode, by_path, msg=path)


class TSKFsInfoFileObjectWithDetectTest(TSKFsInfoTestCase):
    """Tests the FS_Info object with auto-detect Img_Info."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        test_file = os.path.join("test_data", "image.raw")

        # pylint: disable=consider-using-with
        self._file_object = open(test_file, "rb")

        stat_info = os.stat(test_file)
        self._file_size = stat_info.st_size
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size, image_type=pytsk3.TSK_IMG_TYPE_DETECT
        )

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
        test_file = os.path.join("test_data", "image.raw")

        # pylint: disable=consider-using-with
        self._file_object = open(test_file, "rb")

        self._file_size = 1024 * 1024 * 1024 * 1024
        self._img_info = test_lib.FileObjectImageInfo(
            self._file_object, self._file_size
        )

    def testInitialize(self):
        """Test the initialize functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testInitialize(fs_info)

    def testOpenMeta(self):
        """Test the open meta functionality."""
        fs_info = pytsk3.FS_Info(self._img_info, offset=0)
        self._testOpenMeta(fs_info)


if __name__ == "__main__":
    unittest.main()
