#!/usr/bin/env python3
"""Cyclic garbage collection (GC) regression tests for pytsk3.

The struct wrappers participate in cycles via the C-side keepalive fields
(python_object1 / python_object2) that hold parent objects alive for the
lifetime of a borrowed-struct child. Without Py_TPFLAGS_HAVE_GC plus a
tp_traverse and tp_clear implementation, those cycles are unreachable to the
collector and the libtsk handles plus any user payload leak for the process
lifetime.
"""

import gc
import os
import unittest

import pytsk3


class CycleCollectionTest(unittest.TestCase):
    """Test if the struct wrappers participate in cyclic GC.

    img_info._cycle = directory; directory.python_object1 = fs (C keepalive);
    fs.python_object1 = img_info (C keepalive) is a real cycle. Without tp_traverse,
    tp_clear and Py_TPFLAGS_HAVE_GC the libtsk handle (plus any user payload) leaks for
    the process lifetime.
    """

    # pylint: disable=protected-access

    def testCycleIsCollected(self):
        """Test if the struct wrappers participate in cyclic GC."""
        sentinel_alive = [True]

        class Sentinel:
            """Sentinel for testing."""

            def __del__(self):
                """Destructor."""
                sentinel_alive[0] = False

        class CycleImg(pytsk3.Img_Info):
            """Img_Info for testing."""

        def Build():
            """Create the necessary objects for testing."""
            test_file = os.path.join("test_data", "image.raw")
            img_info = CycleImg(url=test_file)

            # Precondition: GC must track the wrapper or the cycle below
            # is unreachable to the collector regardless of fix correctness.
            assert gc.is_tracked(img_info), "wrapper must be GC-tracked"

            fs_info = pytsk3.FS_Info(img_info)
            directory = fs_info.open_dir("/")

            # Set up cyclic references:
            # img_info -> directory -> fs_info (python_object1) -> img_info

            # pylint: disable=attribute-defined-outside-init
            img_info._cycle = directory
            img_info._sentinel = Sentinel()

        Build()

        gc.collect()
        self.assertFalse(
            sentinel_alive[0],
            "cycle through python_object1 keepalive was not collected",
        )


if __name__ == "__main__":
    unittest.main()
