#!/usr/bin/env python3
"""Security regression tests for pytsk3."""

import os
import unittest

import pytsk3


class OversizedReadImgInfo(pytsk3.Img_Info):
    """Pytsk3 image object with a read that returns more data than requested."""

    def __init__(self, file_object, file_size):
        """Initializes an image object."""
        # pytsk3.Img_Info does not let you set attributes after initialization.
        self._file_object = file_object
        self._file_size = file_size

        self.max_overflow = 0

        # Using the old parent class invocation style otherwise some versions
        # of pylint complain also setting type to RAW or EXTERNAL to make sure
        # Img_Info does not do detection.
        pytsk3.Img_Info.__init__(self, url="", type=pytsk3.TSK_IMG_TYPE_RAW)

    def get_size(self):
        """Retrieves the size.

        Returns:
          int: size.
        """
        return self._file_size

    def read(self, offset, size):
        """Reads a byte string from the image object at the specified offset.

        Args:
          offset (int): offset where to start reading.
          size (int): number of bytes to read.

        Returns:
          bytes: data read.
        """
        self._file_object.seek(offset, os.SEEK_SET)
        data = self._file_object.read(size)

        # Return 4 times what libtsk asked for. The C-side memcpy bound is what
        # stops this from corrupting libtsk's cache slot.
        overflow_data = data + b"\xff" * len(data) * 3

        self.max_overflow = max(self.max_overflow, len(overflow_data) - size)
        return overflow_data


class HeapOverflowOnProxiedReadTest(unittest.TestCase):
    """Test restriction of proxied read callback.

    ProxiedImg_Info_read used to memcpy(buf, tmp_buff, tmp_len) with no upper
    bound on tmp_len, where tmp_len comes from the bytes object the Python
    override returned. A subclass returning more bytes than libtsk requested
    overflowed the libtsk-allocated heap buffer.

    class_parser.py now restricts tmp_len to the requested size before the copy.
    Returning oversized bytes must therefore be truncated rather than corrupting
    heap memory.
    """

    def testOversizedRead(self):
        """Test restriction of proxied read callback."""
        # The proxied callback path is only invoked when libtsk itself calls
        # back into the Python subclass's read() (e.g. during FS_Info
        # auto-detection). A direct `img_info.read(...)` from Python uses normal
        # MRO and does not exercise the C memcpy. So the test feeds the real test
        # image through a subclass whose read() is instrumented to return way more
        # bytes than libtsk asks for. If the memcpy bound were missing, libtsk's
        # cache slot would be corrupted and FS_Info would either crash or read
        # garbage.

        test_file = os.path.join("test_data", "image.raw")
        file_size = os.stat(test_file).st_size

        with open(test_file, "rb") as file_object:
            img_info = OversizedReadImgInfo(file_object, file_size)
            try:
                # FS_Info construction makes libtsk call img_info.read() multiple times
                # to identify the filesystem. With the restriction in place this
                # succeeds and returns valid file metadata. Without the restriction this
                # either crashes or scrambles cache state, making the directory listing
                # wrong, empty or corrupt.

                fs_info = pytsk3.FS_Info(img_info, offset=0)
                directory = fs_info.open_dir("/")

                self.assertGreater(
                    img_info.max_overflow, 0, "subclass never overflowed"
                )
                names = sorted(
                    entry.info.name.name
                    for entry in directory
                    if entry.info and entry.info.name
                )
                self.assertIn(b"passwords.txt", names)

            finally:
                img_info.close()


class ExitMethodDoesNotKillInterpreterTest(unittest.TestCase):
    """Test if FS_Info.exit() does not kill the Python interpreter.

    FS_Info_exit used to call exit(0), letting any caller of fs_info.exit()
    terminate the host Python interpreter. Now it must raise a clean RuntimeError
    instead.
    """

    def testExitRaisesRuntimeError(self):
        """Test if FS_Info.exit() does not kill the Python interpreter."""
        test_file = os.path.join("test_data", "image.raw")
        img_info = pytsk3.Img_Info(url=test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)

        with self.assertRaises(RuntimeError):
            fs_info.exit()

        # Reach into pytsk after exit() to test the process did not exit.

        file_object = fs_info.open_meta(15)
        self.assertEqual(file_object.info.meta.size, 116)


class StructWrapperPropertyBaseAccessTest(unittest.TestCase):
    """Test the property getter "self->base == NULL" guard of struct wrappers.

    Direct instantiation, such as pytsk3.TSK_FS_BLOCK() leaves self->base set
    to NULL. Property access used to dereference NULL and crash. It must now
    raise RuntimeError instead.
    """

    _CANDIDATE_ATTRIBUTES = {
        "TSK_FS_BLOCK": ("tag", "fs_info", "addr", "flags"),
        "TSK_FS_INFO": ("tag", "block_count", "block_size", "inum_count"),
        "TSK_FS_NAME": ("name", "meta_addr", "flags"),
        "TSK_FS_META": ("addr", "size", "mode", "type"),
        "TSK_FS_FILE": ("tag", "fs_info"),
        "TSK_FS_ATTR": ("flags", "name", "type", "id", "size"),
        "TSK_FS_ATTR_RUN": ("addr", "len", "offset", "flags"),
        "TSK_VS_INFO": ("tag", "vstype", "block_size", "offset"),
        "TSK_VS_PART_INFO": ("tag", "addr", "start", "len", "flags"),
    }

    def _GetCandidateAttributes(self, class_name):
        """Retrieves attribute candidates for testing.

        The list of property names per struct is static, so the test does not have
        to call dir() on an unbound instance. A call to dir() would be routed
        through the struct wrapper's __getattr__ which itself trips the
        "self->base == NULL" guard, before we get a chance to test the properties.

        Args:
          class_name (str): name of the struct wrapper class.
        """
        return self._CANDIDATE_ATTRIBUTES.get(class_name, ())

    def testEveryStructWrapperRaisesOnUnboundAccess(self):
        """Test the property getter "self->base == NULL" guard."""
        classes = [
            candidate
            for candidate in self._CANDIDATE_ATTRIBUTES
            if hasattr(pytsk3, candidate)
        ]
        self.assertGreater(len(classes), 0, "no struct wrapper classes found")

        guard_hits = 0
        for class_name in classes:
            cls = getattr(pytsk3, class_name)

            try:
                instance = cls()
            except TypeError:
                continue

            for attribute_name in self._GetCandidateAttributes(class_name):
                try:
                    getattr(instance, attribute_name)
                except (AttributeError, OSError, TypeError):
                    pass

                except RuntimeError:
                    guard_hits += 1

        self.assertGreater(
            guard_hits, 0, '"self->base == NULL" guard was never exercised'
        )


class ErrorMessageWithoutLibtskErrnoTest(unittest.TestCase):
    """Test the safe_tsk_error_get() helper.

    RaiseError(..., "%s", tsk_error_get()) used to pass a NULL pointer to %s when
    libtsk recorded no t_errno -- undefined behavior on glibc. The wrapper now
    substitutes a placeholder string.
    """

    def testInvalidImageProducesUsableMessage(self):
        """Test the safe_tsk_error_get() helper."""
        test_file = os.path.join("test_data", "image.raw")
        img_info = pytsk3.Img_Info(url=test_file)

        # Hitting an internal libtsk error path that may not set t_errno ultimately
        # raises through RaiseError; the resulting Python exception message must be
        # a non-empty string with no NUL byte and no literal "(null)" leak from a
        # NULL-on-%s formatter.

        with self.assertRaises(OSError) as exception:
            pytsk3.FS_Info(img_info, offset=999_999_999_999)

        message = str(exception.exception)
        self.assertTrue(message)
        self.assertNotIn("\x00", message)
        self.assertNotIn("(null)", message)


if __name__ == "__main__":
    unittest.main()
