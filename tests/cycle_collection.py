#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Cyclic-GC regression test for the generated pytsk3 wrappers.

The wrappers participate in cycles via the C-side keepalive fields
(python_object1 / python_object2) that hold parent objects alive
for the lifetime of a borrowed-struct child. Without
Py_TPFLAGS_HAVE_GC plus a real tp_traverse / tp_clear, those cycles
are unreachable to the collector and the libtsk handles plus any
user payload leak for the process lifetime. This pattern is the
dominant trigger in every dfvfs / plaso / GRR pipeline.
"""

import gc
import os
import unittest

import pytsk3


_TEST_IMAGE = os.path.join('test_data', 'image.raw')


class CycleCollectionTest(unittest.TestCase):
  """Wrapper objects participate in cyclic GC.

  img._cycle = directory; directory.python_object1 = fs (C keepalive);
  fs.python_object1 = img (C keepalive) is a real cycle. Without
  tp_traverse / tp_clear / Py_TPFLAGS_HAVE_GC the libtsk handle (plus
  any user payload) leaks for the process lifetime.
  """

  def testCycleIsCollected(self):
    sentinel_alive = [True]

    class Sentinel:
      def __del__(self_inner):
        sentinel_alive[0] = False

    class CycleImg(pytsk3.Img_Info):
      pass

    def build():
      img = CycleImg(_TEST_IMAGE)
      # Precondition: GC must track the wrapper or the cycle below
      # is unreachable to the collector regardless of fix correctness.
      assert gc.is_tracked(img), 'wrapper must be GC-tracked'
      fs = pytsk3.FS_Info(img)
      d = fs.open_dir('/')
      img._cycle = d            # img -> d -> fs (python_object1) -> img
      img._sentinel = Sentinel()

    build()
    gc.collect()
    self.assertFalse(
        sentinel_alive[0],
        'cycle through python_object1 keepalive was not collected')


if __name__ == '__main__':
  unittest.main()
