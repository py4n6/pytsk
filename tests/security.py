#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Security regression tests for pytsk3.

Each test pins a previously-fixed vulnerability so that a future
refactor cannot silently reintroduce it.
"""

import io
import os
import unittest

import pytsk3


_TEST_IMAGE = os.path.join('test_data', 'image.raw')


class HeapOverflowOnProxiedReadTest(unittest.TestCase):
  """Pin the bound on Python-supplied bytes from a subclass read().

  ProxiedImg_Info_read used to memcpy(buf, tmp_buff, tmp_len) with no
  upper bound on tmp_len, where tmp_len comes from the bytes object
  the Python override returned. A subclass returning more bytes than
  libtsk requested overflowed the libtsk-allocated heap buffer.

  The codegen now clamps tmp_len to the requested length before the
  copy. Returning oversized bytes must therefore be truncated rather
  than corrupting heap memory.
  """

  def testOversizedSubclassReadIsClamped(self):
    # The proxied callback path is only invoked when libtsk itself
    # calls back into the Python subclass's read() (e.g. during
    # FS_Info auto-detection). A direct `img.read(...)` from Python
    # uses normal MRO and does not exercise the C memcpy. So the
    # test feeds the real test image through a subclass whose read()
    # is instrumented to return way more bytes than libtsk asks for;
    # if the memcpy bound were missing, libtsk's cache slot would be
    # corrupted and FS_Info would either crash or read garbage.
    file_path = _TEST_IMAGE
    file_size = os.stat(file_path).st_size
    file_object = open(file_path, 'rb')
    self.addCleanup(file_object.close)

    class _OversizedSubclass(pytsk3.Img_Info):

      def __init__(self):
        self._file_object = file_object
        self._file_size = file_size
        self.max_overflow = 0
        super().__init__(url='', type=pytsk3.TSK_IMG_TYPE_RAW)

      def get_size(self):
        return self._file_size

      def read(self, offset, size):
        self._file_object.seek(offset, os.SEEK_SET)
        data = self._file_object.read(size)
        # Return 4x what libtsk asked for. The C-side memcpy bound
        # is what stops this from corrupting libtsk's cache slot.
        # Track the largest overflow we attempted so the assertion
        # below is meaningful even if libtsk asks for tiny sizes.
        bloated = data + b'\xff' * len(data) * 3
        self.max_overflow = max(self.max_overflow, len(bloated) - size)
        return bloated

    img = _OversizedSubclass()
    try:
      # FS_Info construction makes libtsk call img.read() multiple
      # times to identify the filesystem. With the clamp in place
      # this succeeds and returns valid file metadata. Without the
      # clamp this either crashes or scrambles cache state, making
      # the directory listing wrong / empty / corrupt.
      fs = pytsk3.FS_Info(img, offset=0)
      directory = fs.open_dir('/')
      names = sorted(
          entry.info.name.name
          for entry in directory
          if entry.info and entry.info.name)
      # We deliberately returned oversized buffers from every read.
      self.assertGreater(img.max_overflow, 0,
                         'subclass never overflowed -- test inert')
      # Listing must include the well-known fixture entries.
      self.assertIn(b'passwords.txt', names)
    finally:
      img.close()


class ExitMethodDoesNotKillInterpreterTest(unittest.TestCase):
  """Pin the FS_Info.exit() denial-of-service fix.

  FS_Info_exit used to call exit(0), letting any caller of
  fs_info.exit() terminate the host Python interpreter. Now it must
  raise a clean RuntimeError instead.
  """

  def testExitRaisesRuntimeError(self):
    img = pytsk3.Img_Info(url=_TEST_IMAGE)
    fs = pytsk3.FS_Info(img, offset=0)
    with self.assertRaises(RuntimeError):
      fs.exit()
    # Process is still alive; reach into pytsk after exit() to prove
    # we did not just survive in C-side limbo.
    file_object = fs.open_meta(15)
    self.assertEqual(file_object.info.meta.size, 116)


class StructWrapperUninitializedAccessTest(unittest.TestCase):
  """Pin the property-getter NULL-base guard.

  Direct instantiation (e.g. `pytsk3.TSK_FS_BLOCK()`) leaves
  self->base == NULL. Property access used to dereference NULL and
  crash; it must now raise RuntimeError instead.
  """

  def _struct_classes(self):
    candidates = [
        'TSK_FS_BLOCK', 'TSK_FS_INFO', 'TSK_FS_NAME', 'TSK_FS_META',
        'TSK_FS_FILE', 'TSK_FS_ATTR', 'TSK_FS_ATTR_RUN',
        'TSK_VS_INFO', 'TSK_VS_PART_INFO',
    ]
    return [c for c in candidates if hasattr(pytsk3, c)]

  def _candidate_attrs(self, class_name):
    """Static list of property names per struct, so the test does not
    have to call dir() on an unbound instance (dir() routes through
    the wrapper's __getattr__ which itself trips the NULL-base
    guard, before we get a chance to test individual properties).
    """
    return {
        'TSK_FS_BLOCK': ('tag', 'fs_info', 'addr', 'flags'),
        'TSK_FS_INFO': ('tag', 'block_count', 'block_size', 'inum_count'),
        'TSK_FS_NAME': ('name', 'meta_addr', 'flags'),
        'TSK_FS_META': ('addr', 'size', 'mode', 'type'),
        'TSK_FS_FILE': ('tag', 'fs_info'),
        'TSK_FS_ATTR': ('flags', 'name', 'type', 'id', 'size'),
        'TSK_FS_ATTR_RUN': ('addr', 'len', 'offset', 'flags'),
        'TSK_VS_INFO': ('tag', 'vstype', 'block_size', 'offset'),
        'TSK_VS_PART_INFO': ('tag', 'addr', 'start', 'len', 'flags'),
    }.get(class_name, ())

  def testEveryStructWrapperRaisesOnUnboundAccess(self):
    classes = self._struct_classes()
    self.assertGreater(len(classes), 0, 'no struct wrappers found')
    guard_hits = 0
    for class_name in classes:
      cls = getattr(pytsk3, class_name)
      try:
        instance = cls()
      except TypeError:
        # Some classes refuse direct construction; that's fine -- the
        # vulnerability requires a NULL self->base reachable from
        # Python, and refusing __init__ achieves the same end.
        continue
      for attr in self._candidate_attrs(class_name):
        try:
          getattr(instance, attr)
        except RuntimeError:
          # Raised by the NULL-base guard in the property getter
          # prelude. This is the desired behavior.
          guard_hits += 1
        except (AttributeError, TypeError, IOError):
          # Acceptable -- attribute does not exist on this build /
          # version, or the wrapper's __getattr__ refused before
          # reaching the property, both of which still avoid the
          # crash this test is pinning.
          pass
    self.assertGreater(guard_hits, 0,
                       'NULL-base guard was never exercised; test is inert')


class ErrorMessageWithoutLibtskErrnoTest(unittest.TestCase):
  """Pin the safe_tsk_error_get() helper.

  RaiseError(..., "%s", tsk_error_get()) used to pass a NULL pointer
  to %s when libtsk recorded no t_errno -- undefined behavior on
  glibc. The wrapper now substitutes a placeholder string.
  """

  def testInvalidImageProducesUsableMessage(self):
    # Hitting an internal libtsk error path that may not set t_errno
    # ultimately raises through RaiseError; the resulting Python
    # exception message must be a non-empty string with no NUL byte
    # and no literal "(null)" leak from a NULL-on-%s formatter.
    img = pytsk3.Img_Info(url=_TEST_IMAGE)
    with self.assertRaises(IOError) as ctx:
      pytsk3.FS_Info(img, offset=999_999_999_999)
    message = str(ctx.exception)
    self.assertTrue(message)
    self.assertNotIn('\x00', message)
    self.assertNotIn('(null)', message)


if __name__ == '__main__':
  unittest.main()
