#!/usr/bin/env python3
"""Thread-safety and free-threaded Python regression tests for pytsk3.

These exercise patterns that can crash or scramble state when:
  * libtsk is built without TSK_MULTITHREAD_LIB (cache_lock no-ops,
    tsk_error_get backed by a single global), or
  * Python wrapper objects yielded from iteration / property access do
    not hold a strong reference to their parent (use-after-free when
    another thread drops the parent's last visible reference).

Most tests run on both GIL and free-threaded builds. They are
deliberately stress-shaped: a barrier synchronizes all threads to
release together so the contended window is wide enough to surface
races.
"""

import gc
import os
import sys
import threading
import unittest

import pytsk3


def IsFreeThreaded():
    """True when running on a free-threaded Python build."""
    # pylint: disable=protected-access
    return hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()


def HasSubInterpreters():
    """True when the public test_support.interpreters API is available."""
    # pylint: disable=import-error,import-outside-toplevel,unused-import

    try:
        import test.support.interpreters

        return True
    except ImportError:
        pass

    try:
        import _interpreters

        return True
    except ImportError:
        return False


class _RaisingImg(pytsk3.Img_Info):
    """Img_Info whose read() always raises, to exercise pytsk_fetch_error."""

    def __init__(self):
        pytsk3.Img_Info.__init__(self, url="", type=pytsk3.TSK_IMG_TYPE_RAW)

    def close(self):
        return None

    def read(self, offset, size):
        raise RuntimeError("synthetic Python read failure")

    def get_size(self):
        return 1 << 20


class _SharedBytesImg(pytsk3.Img_Info):
    """Bytes-backed Img_Info; per-read lock guarantees callers reach Python."""

    def __init__(self, payload):
        self._payload = payload
        self._size = len(payload)
        self._lock = threading.Lock()
        pytsk3.Img_Info.__init__(self, url="", type=pytsk3.TSK_IMG_TYPE_RAW)

    def close(self):
        with self._lock:
            self._payload = b""

    def read(self, offset, size):
        with self._lock:
            if offset >= len(self._payload):
                return b""
            return self._payload[offset : offset + size]

    def get_size(self):
        return self._size


class ConcurrentTestCase(unittest.TestCase):
    """Base for concurrent test case."""

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "image.raw")
        self._file_size = os.stat(self._test_file).st_size

    def _RunFunctionConcurrently(self, function, count, *args, **kwargs):
        """Run function in count threads released by a shared barrier.

        Returns the list of per-thread results (or the raised exception) in
        thread-start order. Re-raises the first exception seen so the test
        framework reports it.
        """
        barrier = threading.Barrier(count)
        results = [None] * count
        errors = [None] * count

        def Runner(index):
            """Runner function for testing."""
            try:
                barrier.wait()
                results[index] = function(index, *args, **kwargs)
            except BaseException as exception:  # pylint: disable=broad-except
                errors[index] = exception

        threads = [threading.Thread(target=Runner, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        for exception in errors:
            if exception is not None:
                raise exception

        return results


class ModuleFreeThreadingTest(unittest.TestCase):
    """Verifies the module's free-threaded compatibility declaration."""

    # pylint: disable=protected-access

    def testImportSucceeds(self):
        """The module must import without forcing the GIL back on."""
        self.assertTrue(hasattr(pytsk3, "Img_Info"))

    @unittest.skipUnless(IsFreeThreaded(), "requires a free-threaded Python build")
    def testModuleDoesNotForceGil(self):
        """Importing pytsk3 must not flip the interpreter back to GIL mode.

        PyUnstable_Module_SetGIL(module, Py_MOD_GIL_NOT_USED) is the
        declaration that prevents this; if it is missing the runtime would
        re-enable the GIL at import time and sys._is_gil_enabled() would
        return True.
        """
        self.assertFalse(sys._is_gil_enabled())


class ConcurrentImgInfoTest(ConcurrentTestCase):
    """Test reading from Img_Info concurrently.

    Validates that libtsk's per-thread error reporting and cache_lock primitives behave
    correctly under independent use. If TSK_MULTITHREAD_LIB is missing this can scramble
    error state between threads.
    """

    def testIndependentImgInfoReads(self):
        """Test reading from independent Img_Info concurrently."""
        expected = {
            0x5800: b"place,user,passw",
            0x7C00: b"This is another ",
        }

        def Worker(_index):
            """Worker function for testing."""
            img_info = pytsk3.Img_Info(url=self._test_file)

            try:
                for _ in range(50):
                    for offset, value in expected.items():
                        data = img_info.read(offset, len(value))
                        self.assertEqual(data, value)
            finally:
                img_info.close()

        self._RunFunctionConcurrently(Worker, 8)

    def testSharedImgInfoConcurrentRead(self):
        """Test reading from a shared Img_Info concurrently."""
        img_info = pytsk3.Img_Info(url=self._test_file)

        try:

            def Worker(_index):
                """Worker function for testing."""
                for _ in range(100):
                    data = img_info.read(0x5800, 16)
                    self.assertEqual(data, b"place,user,passw")

            self._RunFunctionConcurrently(Worker, 8)
        finally:
            img_info.close()


class ConcurrentFsInfoTest(ConcurrentTestCase):
    """Threads operating concurrently against FS_Info objects.

    libtsk's inode/block caches are accessed under cache_lock when TSK_MULTITHREAD_LIB
    is enabled; this is the test that breaks when that flag was disabled at build time.
    """

    def testIndependentFsInfos(self):
        """Each thread builds its own Img_Info+FS_Info and walks /.

        This is the supported "one libtsk handle per thread" pattern.
        """

        def Worker(_index):
            """Worker function for testing."""
            img_info = pytsk3.Img_Info(url=self._test_file)
            fs_info = pytsk3.FS_Info(img_info, offset=0)
            directory = fs_info.open_dir("/")

            names = []
            for entry in directory:
                if entry.info and entry.info.name:
                    names.append(entry.info.name.name)

            return names

        results = self._RunFunctionConcurrently(Worker, 8)
        # Every thread must have observed the same root listing.
        self.assertTrue(all(r == results[0] for r in results))
        self.assertIn(b"passwords.txt", results[0])

    def testSharedFsInfoConcurrentOpenMeta(self):
        """Threads share an FS_Info and open files by inode in parallel."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)

        def Worker(_index):
            """Worker function for testing."""
            for _ in range(50):
                tsk_file = fs_info.open_meta(15)
                self.assertEqual(tsk_file.info.meta.size, 116)

                # Read the file content fully -- this hits the FS cache.
                data = tsk_file.read_random(0, 116)
                self.assertEqual(len(data), 116)

        self._RunFunctionConcurrently(Worker, 8)


class ParentKeepaliveTest(unittest.TestCase):
    """Children yielded from iteration / properties keep their parent alive.

    Without parent keepalive the underlying libtsk handle can be freed
    while a yielded child is still in use, producing a use-after-free.
    These tests drop every visible reference to the parent and force a
    GC pass before touching the child.
    """

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "image.raw")

    def _yield_first_file(self):
        """Return a File yielded from iteration, with no caller-visible parent."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        directory = fs_info.open_dir("/")
        iterator = iter(directory)
        first = next(iterator)
        # Caller does not receive img_info / fs_info / directory / iterator; only the
        # File. The C-level keepalive must hold them alive.
        return first

    def testIteratedFileSurvivesParentDrop(self):
        """A File yielded by Directory iteration must outlive its FS_Info."""
        tsk_file = self._yield_first_file()

        # Force any cyclic collection now -- if our keepalive is wrong the
        # FS_Info / Img_Info would be reclaimed here.
        gc.collect()

        self.assertIsNotNone(tsk_file.info)

        if tsk_file.info.name:
            # Touching the borrowed name buffer reaches into FS-owned memory.
            self.assertIsNotNone(tsk_file.info.name.name)

    def testOpenedFileSurvivesParentDrop(self):
        """A File from FS_Info.open_meta must outlive its FS_Info."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        tsk_file = fs_info.open_meta(15)

        del fs_info
        del img_info

        gc.collect()

        # passwords.txt is 116 bytes at inode 15 in the fixture image.
        data = tsk_file.read_random(0, 16)
        self.assertEqual(data, b"place,user,passw")

    def testDirectoryFromOpenDirSurvivesParentDrop(self):
        """A Directory from FS_Info.open_dir must outlive its FS_Info."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        directory = fs_info.open_dir("/")

        del fs_info
        del img_info

        gc.collect()

        names = [
            entry.info.name.name
            for entry in directory
            if entry.info and entry.info.name
        ]
        self.assertIn(b"passwords.txt", names)

    def testStructGetterSurvivesParentDrop(self):
        """A borrowed struct from a property getter must outlive its parent.

        file.info is a borrowed pyTSK_FS_FILE pointer into FS-owned memory.
        Releasing the File wrapper must not invalidate the borrowed view.
        """
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        tsk_file = fs_info.open_meta(15)
        info = tsk_file.info
        meta = info.meta

        del tsk_file
        del fs_info
        del img_info

        gc.collect()

        self.assertEqual(meta.size, 116)


class ConcurrentParentDropTest(unittest.TestCase):
    """One thread iterates while another drops the parent reference.

    This is the multi-threaded version of ParentKeepaliveTest. It only
    meaningfully races on free-threaded builds, but is harmless on the
    GIL build (just exercises the keepalive path under thread switches).
    """

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "image.raw")

    def testReadAfterParentDroppedOnOtherThread(self):
        """Test read after parent object was dropped on an other thread."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        tsk_file = fs_info.open_meta(15)

        holder = {"fs_info": fs_info, "img_info": img_info}

        def Reader(_index):
            """Reader function for testing."""
            for _ in range(100):
                data = tsk_file.read_random(0, 16)
                self.assertEqual(data, b"place,user,passw")

        def Dropper(_index):
            """Dropper function for testing."""
            # Drop visible parents while the reader is mid-flight; the
            # tks_file's python_object1 keepalive must keep the libtsk
            # handle alive until the tks_file itself is released.
            holder.clear()
            gc.collect()

        barrier = threading.Barrier(2)
        errors = []

        def Runner(target, index):
            """Runner function for testing."""
            try:
                barrier.wait()
                target(index)
            except BaseException as exception:  # pylint: disable=broad-except
                errors.append(exception)

        threads = [
            threading.Thread(target=Runner, args=(Reader, 0)),
            threading.Thread(target=Runner, args=(Dropper, 1)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise errors[0]


class ConcurrentErrorPathTest(ConcurrentTestCase):
    """Test error handling (tsk_error_get) concurrently.

    When TSK_MULTITHREAD_LIB is missing libtsk falls back to a single
    global TSK_ERROR_INFO; concurrent failing calls then scramble each
    other's errno + errstr buffers. We trigger a known-bogus open in
    many threads at once and assert the resulting Python exception
    message is well-formed every time.
    """

    def testConcurrentInvalidOpens(self):
        """Test error handling (tsk_error_get) concurrently."""
        img_info = pytsk3.Img_Info(url=self._test_file)

        def Worker(index):
            """Worker function for testing."""
            seen_errors = 0
            for _ in range(50):
                try:
                    # Inode 19 does not exist in the fixture; this consistently
                    # raises IOError and writes to libtsk's error buffer.
                    fs_info = pytsk3.FS_Info(img_info, offset=0)
                    fs_info.open_meta(19)

                except IOError as exception:
                    seen_errors += 1

                    # The string must be intact (no NUL truncation, no garbage)
                    # even when other threads are racing the same error path.
                    message = str(exception)

                    self.assertTrue(message)
                    self.assertNotIn("\x00", message)

            self.assertEqual(seen_errors, 50, f"thread {index} lost errors")

        self._RunFunctionConcurrently(Worker, 8)


class ConcurrentVolumeInfoTest(ConcurrentTestCase):
    """Test iterating Volume_Info concurrently.

    With the parent keepalive, the part wrapper must remain valid after Volume_Info
    and Img_Info go out of scope.
    """

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "tsk_volume_system.raw")

    def testIndependentVolumeInfos(self):
        """Test iterating independent Volume_Info concurrently."""

        def Worker(_index):
            """Worker function for testing."""
            img_info = pytsk3.Img_Info(url=self._test_file)
            vs_info = pytsk3.Volume_Info(img_info)
            return [part.addr for part in vs_info]

        results = self._RunFunctionConcurrently(Worker, 8)
        self.assertTrue(all(r == results[0] for r in results))
        self.assertGreater(len(results[0]), 0)

    def testVolumePartSurvivesParentDrop(self):
        """Test iterating shared Volume_Info concurrently."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        vs_info = pytsk3.Volume_Info(img_info)
        parts = list(vs_info)

        del vs_info
        del img_info

        gc.collect()

        # Touching addr / start / len / desc reaches into VS-owned memory.
        for part in parts:
            _ = part.addr
            _ = part.start
            _ = part.len


class CloseDuringReadTest(unittest.TestCase):
    """Test Img_Info close() while another thread is in the middle of read().

    Img_Info_read takes the per-instance state_lock around the img_is_open check and
    the actual tsk_img_read call; Img_Info_close takes the same lock while flipping
    img_is_open. As a result a close() call cannot tear state down mid-read, and any
    read started after close has flipped the flag observes a clean IOError.
    """

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "image.raw")

    def testCloseConcurrentWithReader(self):
        """Test Img_Info close() while another thread is in the middle of read()."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        stop = threading.Event()
        errors = []

        def Reader():
            """Reader function for testing."""
            while not stop.is_set():
                try:
                    # Either succeeds with the right bytes, or raises a clean
                    # IOError once close() lands. Anything else (segfault,
                    # garbage bytes) is a bug.
                    data = img_info.read(0x5800, 16)
                    if data:
                        self.assertEqual(data, b"place,user,passw")
                except IOError:
                    return  # post-close path
                except BaseException as exception:  # pylint: disable=broad-except
                    errors.append(exception)
                    return

        threads = [threading.Thread(target=Reader) for _ in range(4)]
        for thread in threads:
            thread.start()

        # Let readers spin up briefly, then close from this thread.
        threading.Event().wait(0.05)
        img_info.close()

        stop.set()
        for thread in threads:
            thread.join()
        if errors:
            raise errors[0]


class SharedFileConcurrentReadTest(ConcurrentTestCase):
    """Test reading a shared file concurrently.

    pytsk3 does not synchronize File.read_random itself; libtsk's FS
    cache_lock is what serializes the underlying read. This test
    exercises that path -- if libtsk's cache_lock were a no-op (the
    pre-fix state) the resulting bytes would scramble across threads.
    """

    def testSharedFileReadRandom(self):
        """Test reading a shared file concurrently."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        tsk_file = fs_info.open_meta(15)

        # Snapshot the full file once (uncontended) and use it as the
        # ground truth for every concurrent read below.
        expected_data = tsk_file.read_random(0, 116)
        self.assertEqual(len(expected_data), 116)

        def Worker(_index):
            """Worker function for testing."""
            for _ in range(200):
                for data_offset in (0, 16, 32, 48, 64, 80):
                    data = tsk_file.read_random(data_offset, 16)
                    self.assertEqual(
                        data, expected_data[data_offset : data_offset + 16]
                    )

        self._RunFunctionConcurrently(Worker, 8)


class RecursiveWalkStressTest(ConcurrentTestCase):
    """Test recursing a shared file system concurrently.

    Long-running concurrent allocation churn exercises every yield path through
    new_class_wrapper, StructWrapper.assign, and dealloc. A parent-keepalive
    imbalance surfaces as a leak or immediate crash.
    """

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

    def testRecursiveWalkStress(self):
        """Test recursing a shared file system concurrently."""

        def Worker(_index):
            """Worker function for testing."""
            img_info = pytsk3.Img_Info(url=self._test_file)
            fs_info = pytsk3.FS_Info(img_info, offset=0)

            total = 0
            for _ in range(20):
                directory = fs_info.open_dir("/")
                total += sum(1 for _ in self._WalkFileSystem(directory))
            return total

        results = self._RunFunctionConcurrently(Worker, 8)
        # Same entry count across all threads -- mismatch implies a
        # cursor / lock bug in iteration.
        self.assertTrue(all(r == results[0] for r in results), results)
        self.assertGreater(results[0], 0)


class GcUnderLoadTest(ConcurrentTestCase):
    """Test garbage collection (GC) in a hot loop.

    Cyclic GC visits all tracked objects and may run __del__ / tp_dealloc on things
    that became unreachable since the last collection. A bug in the parent keepalive,
    such as forgetting to Py_IncRef in new_class_wrapper) would surface here as a UAF
    when GC reaps a parent the worker is still using.
    """

    def testGcConcurrentWithIteration(self):
        """Test GC in a hot loop."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        stop = threading.Event()
        errors = []

        def GcWorker():
            """Worker function for testing."""
            while not stop.is_set():
                gc.collect()

        def IterWorker(_index):
            """Worker function for testing."""
            try:
                for _ in range(100):
                    directory = fs_info.open_dir("/")
                    names = []
                    for entry in directory:
                        if entry.info and entry.info.name:
                            names.append(entry.info.name.name)
                    self.assertIn(b"passwords.txt", names)
            except BaseException as exception:  # pylint: disable=broad-except
                errors.append(exception)

        gc_thread = threading.Thread(target=GcWorker)
        gc_thread.start()

        try:
            self._RunFunctionConcurrently(IterWorker, 4)
        finally:
            stop.set()
            gc_thread.join()
        if errors:
            raise errors[0]


class GilStaysOffTest(unittest.TestCase):
    """Test if sys._is_gil_enabled() remains false across pytsk3 operations.

    testModuleDoesNotForceGil only checks the post-import state. A bug that re-enables
    the GIL on a specific code path (e.g. an unguarded private API call) wouldn't be
    caught there. Hammer a representative mix of pytsk3 operations and confirm the GIL
    stays off the entire time.
    """

    # pylint: disable=protected-access

    def setUp(self):
        """Sets up the needed objects used throughout the test."""
        self._test_file = os.path.join("test_data", "image.raw")

    @unittest.skipUnless(IsFreeThreaded(), "requires a free-threaded Python build")
    def testGilStaysOffAcrossOperations(self):
        """Test if sys._is_gil_enabled() remains false across pytsk3 operations."""
        self.assertFalse(sys._is_gil_enabled())

        img_info = pytsk3.Img_Info(url=self._test_file)

        self.assertFalse(sys._is_gil_enabled())

        fs_info = pytsk3.FS_Info(img_info, offset=0)

        self.assertFalse(sys._is_gil_enabled())

        directory = fs_info.open_dir("/")

        self.assertFalse(sys._is_gil_enabled())

        for entry in directory:
            if entry.info and entry.info.meta:
                _ = entry.info.meta.size

        self.assertFalse(sys._is_gil_enabled())

        tsk_file = fs_info.open_meta(15)

        data = tsk_file.read_random(0, 16)
        self.assertEqual(data, b"place,user,passw")

        self.assertFalse(sys._is_gil_enabled())

        img_info.close()

        self.assertFalse(sys._is_gil_enabled())


class IteratorCursorThreadSafetyTest(ConcurrentTestCase):
    """Test iterating Directory concurrently.

    Before the per-instance iter_lock was introduced, two threads iterating the same
    Directory would race on self->current and produce skipped/duplicated entries. With
    iter_lock each entry index is consumed exactly once across all threads, so the
    union of yields is the full directory listing.
    """

    def testSharedDirectoryIterator(self):
        """Test iterating independent Directory concurrently."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)
        directory = fs_info.open_dir("/")

        # Build a baseline: how many entries are in /. Use a fresh Directory so the
        # shared one below starts at cursor 0 (the Cconstructor sets current = 0; we
        # deliberately do not call iter() here because that would also reset).
        baseline = sum(1 for _ in fs_info.open_dir("/"))

        yielded = []
        yielded_lock = threading.Lock()

        def Worker(_index):
            """Worker function for testing."""
            # Note: do NOT call iter(directory) here. Directory is its own iterator and
            # __iter__ resets the cursor under iter_lock, which is correct behavior for
            # "for x in d:" in a single thread, but would defeat the test that all
            # workers consume from the same cursor sequence.
            while True:
                try:
                    # pylint: disable=unnecessary-dunder-call
                    entry = directory.__next__()
                except StopIteration:
                    return

                with yielded_lock:
                    yielded.append(entry)

        self._RunFunctionConcurrently(Worker, 4)

        # Cursor was advanced exactly baseline times across all workers. An off-by-one
        # (missed lock release, double-advance) would change this count; a true race
        # (skipping the cap-at-INT_MAX check) could overshoot indefinitely.
        self.assertEqual(len(yielded), baseline)


class SubinterpreterImportTest(unittest.TestCase):
    """Test if pytsk3 cleanly initialize inside a subinterpreter.

    tsk_init() is wrapped in std::call_once so the C class templates
    are only initialized once across all interpreters. Importing
    pytsk3 in a fresh subinterpreter exercises that path and surfaces
    any cross-subinterpreter state leak.

    The subinterpreter API has shifted across Python versions:
      * 3.11: only the private `_xxsubinterpreters` module, with a
        `.run_string(id, script)` signature.
      * 3.12-3.13: `test.support.interpreters` available but the
        Interpreter object exposes `.run(script)`, not `.exec(...)`.
        These versions also enforce PEP 489: single-phase-init C
        modules (which pytsk3 still is) cannot load into a
        subinterpreter, so this test is a no-op skip there.
      * 3.14+: `interp.exec(script)` is the documented method, and the
        default policy here permits the load.

    This test probes each API in turn and skips when none works.
    """

    _TEST_IMAGE = os.path.join("test_data", "image.raw")

    _SUBINTERP_SCRIPT = (
        "import pytsk3\n"
        "img_info = pytsk3.Img_Info(url=" + repr(_TEST_IMAGE) + ")\n"
        "assert img_info.get_size() == 102400\n"
        "fs_info = pytsk3.FS_Info(img_info, offset=0)\n"
        "f = fs_info.open_meta(15)\n"
        "assert f.read_random(0, 16) == b'place,user,passw'\n"
    )

    def _IsSubInterpreterLoadUnsupported(self, exception):
        """Detect 'module does not support loading in subinterpreters'.

        Python 3.12+ refuses to load single-phase-init C extension modules
        into a subinterpreter unless they declare the
        Py_mod_multiple_interpreters slot. pytsk3 still uses single-phase
        init, so this ImportError is expected on 3.12 / 3.13. The message
        bubbles up wrapped (e.g. as _xxsubinterpreters.RunFailedError) so
        we have to match on the inner ImportError text.
        """
        text = str(exception)

        return (
            "does not support loading in subinterpreters" in text
            or "is not allowed in subinterpreters" in text
        )

    @unittest.skipUnless(HasSubInterpreters(), "subinterpreter API not available")
    def testImportInSubinterpreter(self):
        """Test if pytsk3 cleanly initialize inside a subinterpreter."""
        # pylint: disable=import-error,import-outside-toplevel,unused-import

        # Try the public API first.
        try:
            from test.support import interpreters  # type: ignore
        except ImportError:
            interpreters = None  # pylint: disable=invalid-name

        if interpreters is not None:
            interp = interpreters.create()
            try:
                runner = getattr(interp, "exec", None) or getattr(interp, "run", None)
                if runner is None:
                    self.skipTest(
                        "test.support.interpreters has no exec/run on this build"
                    )

                try:
                    runner(self._SUBINTERP_SCRIPT)
                except Exception as exception:  # pylint: disable=broad-except
                    if self._IsSubInterpreterLoadUnsupported(exception):
                        self.skipTest(
                            "pytsk3 uses single-phase init; this Python version "
                            "forbids loading such modules in a subinterpreter"
                        )
                    raise

                return

            finally:
                close = getattr(interp, "close", None)
                if close is not None:
                    close()

        # Fall back to the private API. The module name and run_string signature both
        # vary across versions; tolerate either.
        try:
            import _interpreters

            private = _interpreters
        except ImportError:
            try:
                import _xxsubinterpreters

                private = _xxsubinterpreters
            except ImportError:
                self.skipTest("no usable subinterpreter API")

        interp_id = private.create()

        try:
            run_string = getattr(private, "run_string", None)
            if run_string is None:
                self.skipTest("private subinterpreter API has no run_string")

            try:
                run_string(interp_id, self._SUBINTERP_SCRIPT)
            except Exception as exception:  # pylint: disable=broad-except
                if self._IsSubInterpreterLoadUnsupported(exception):
                    self.skipTest(
                        "pytsk3 uses single-phase init; this Python version "
                        "forbids loading such modules in a subinterpreter"
                    )
                raise

        finally:
            private.destroy(interp_id)


class ProxiedReadConcurrencyTest(unittest.TestCase):
    """Python-backed Img_Info hammered through libtsk's proxied read path.

    Covers Img_Info_read no longer holding state_lock across tsk_img_read
    (Python callback's own lock cannot ABBA) and the python_object2 swap
    in proxied Wrapper-returning callbacks (critical-section-protected
    on 3.13+ against double-decref).
    """

    def testConcurrentReadsThroughProxiedCallback(self):
        """Concurrent reads + bounded join: covers correctness AND no deadlock."""
        test_file = os.path.join("test_data", "image.raw")
        with open(test_file, "rb") as f:
            img_info = _SharedBytesImg(f.read())

        try:

            def Worker(_index):
                """Worker function for testing."""
                for _ in range(20):
                    fs_info = pytsk3.FS_Info(img_info, offset=0)
                    tsk_file = fs_info.open_meta(15)

                    self.assertEqual(tsk_file.info.meta.size, 116)

                    data = tsk_file.read_random(0, 116)
                    self.assertEqual(len(data), 116)

            threads = [threading.Thread(target=Worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()

            # Bounded join so a deadlock fails the test instead of hanging.
            for t in threads:
                t.join(timeout=30)
            for t in threads:
                self.assertFalse(t.is_alive(), "worker deadlocked")
        finally:
            img_info.close()


class ReimportClassRegistryTest(ConcurrentTestCase):
    """Concurrent class-registry lookups must not see a torn TOTAL_CCLASSES.

    TOTAL_CCLASSES is now std::atomic<int> (release writers / acquire readers); legacy
    plain-int reads could observe a half-zeroed entry during a re-init.
    """

    def testRegistryStableUnderConcurrentLookups(self):
        """Test concurrent class-registry lookups."""
        img_info = pytsk3.Img_Info(url=self._test_file)
        fs_info = pytsk3.FS_Info(img_info, offset=0)

        try:

            def Worker(_index):
                """Worker function for testing."""
                for _ in range(200):
                    tsk_file = fs_info.open_meta(15)

                    self.assertIsNotNone(tsk_file.info.meta)

                    # Iteration drives Wrapper construction through the registry.
                    for _attr in tsk_file:
                        pass

            self._RunFunctionConcurrently(Worker, 8)
        finally:
            img_info.close()


class ProxiedExceptionPathTest(unittest.TestCase):
    """Test if exceptions raised in a proxied Python callback reaches Python.

    On 3.12+ pytsk_fetch_error uses PyErr_GetRaisedException / SetRaisedException; the
    legacy Fetch/Restore triple was removed in 3.14. Verifies the modern path actually
    transports the exception.
    """

    def testRaiseInPythonReadIsObserved(self):
        """Test if exceptions raised in a proxied Python callback reaches Python."""
        img_info = _RaisingImg()
        try:
            with self.assertRaises((IOError, OSError, RuntimeError)):
                _ = pytsk3.FS_Info(img_info, offset=0)
        finally:
            img_info.close()


class CycleCollectionTest(unittest.TestCase):
    """Test if wrapper objects participate in cyclic garbage collection (GC).

    img_info._cycle = directory; directory.python_object1 = fs_info (C keepalive);
    fs_info.python_object1 = img_info (C keepalive) is a real cycle. Without
    tp_traverse, tp_clear and Py_TPFLAGS_HAVE_GC the libtsk handle (plus any user
    payload) leaks for the process lifetime.
    """

    # pylint: disable=protected-access

    def testCycleIsCollected(self):
        """Test if wrapper objects participate in cyclic GC."""
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
            img_info = CycleImg(test_file)

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
