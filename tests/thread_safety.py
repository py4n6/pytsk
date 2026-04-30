#!/usr/bin/python
# -*- coding: utf-8 -*-
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

import test_lib


_TEST_IMAGE = os.path.join('test_data', 'image.raw')
_TEST_VOLUME = os.path.join('test_data', 'tsk_volume_system.raw')


def _is_free_threaded():
  """True when running on a free-threaded Python build."""
  return hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()


def _run_concurrently(target, count, *args, **kwargs):
  """Run target in count threads released by a shared barrier.

  Returns the list of per-thread results (or the raised exception) in
  thread-start order. Re-raises the first exception seen so the test
  framework reports it.
  """
  barrier = threading.Barrier(count)
  results = [None] * count
  errors = [None] * count

  def runner(index):
    try:
      barrier.wait()
      results[index] = target(index, *args, **kwargs)
    except BaseException as exc:  # pylint: disable=broad-except
      errors[index] = exc

  threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join()

  for exc in errors:
    if exc is not None:
      raise exc
  return results


class ModuleFreeThreadingTest(unittest.TestCase):
  """Verifies the module's free-threaded compatibility declaration."""

  def testImportSucceeds(self):
    """The module must import without forcing the GIL back on."""
    self.assertTrue(hasattr(pytsk3, 'Img_Info'))

  @unittest.skipUnless(
      _is_free_threaded(),
      'requires a free-threaded Python build')
  def testModuleDoesNotForceGil(self):
    """Importing pytsk3 must not flip the interpreter back to GIL mode.

    PyUnstable_Module_SetGIL(module, Py_MOD_GIL_NOT_USED) is the
    declaration that prevents this; if it is missing the runtime would
    re-enable the GIL at import time and sys._is_gil_enabled() would
    return True.
    """
    self.assertFalse(sys._is_gil_enabled())


class ConcurrentImgInfoTest(unittest.TestCase):
  """Threads each operating on independent Img_Info instances."""

  def setUp(self):
    self._test_file = _TEST_IMAGE
    self._file_size = os.stat(self._test_file).st_size

  def testIndependentImgInfoReads(self):
    """Each thread builds its own Img_Info and reads concurrently.

    Validates that libtsk's per-thread error reporting and
    cache_lock primitives behave correctly under independent use --
    if TSK_MULTITHREAD_LIB is missing this can scramble error state
    between threads.
    """
    expected = {
        0x5800: b'place,user,passw',
        0x7c00: b'This is another ',
    }

    def worker(_index):
      img = pytsk3.Img_Info(url=self._test_file)
      try:
        for _ in range(50):
          for offset, value in expected.items():
            self.assertEqual(img.read(offset, len(value)), value)
      finally:
        img.close()

    _run_concurrently(worker, 8)

  def testSharedImgInfoConcurrentRead(self):
    """Many threads share one Img_Info and call read() concurrently."""
    img = pytsk3.Img_Info(url=self._test_file)
    try:

      def worker(_index):
        for _ in range(100):
          self.assertEqual(
              img.read(0x5800, 16), b'place,user,passw')

      _run_concurrently(worker, 8)
    finally:
      img.close()


class ConcurrentFsInfoTest(unittest.TestCase):
  """Threads operating concurrently against FS_Info objects."""

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testIndependentFsInfos(self):
    """Each thread builds its own Img_Info+FS_Info and walks /.

    This is the supported "one libtsk handle per thread" pattern.
    """

    def worker(_index):
      img = pytsk3.Img_Info(url=self._test_file)
      fs = pytsk3.FS_Info(img, offset=0)
      directory = fs.open_dir('/')
      names = []
      for entry in directory:
        if entry.info and entry.info.name:
          names.append(entry.info.name.name)
      return names

    results = _run_concurrently(worker, 8)
    # Every thread must have observed the same root listing.
    self.assertTrue(all(r == results[0] for r in results))
    self.assertIn(b'passwords.txt', results[0])

  def testSharedFsInfoConcurrentOpenMeta(self):
    """Threads share an FS_Info and open files by inode in parallel.

    libtsk's inode/block caches are accessed under cache_lock when
    TSK_MULTITHREAD_LIB is enabled; this is the test that breaks when
    that flag was disabled at build time.
    """
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)

    def worker(_index):
      for _ in range(50):
        file_object = fs.open_meta(15)
        self.assertEqual(file_object.info.meta.size, 116)
        # Read the file content fully -- this hits the FS cache.
        data = file_object.read_random(0, 116)
        self.assertEqual(len(data), 116)

    _run_concurrently(worker, 8)


class ParentKeepaliveTest(unittest.TestCase):
  """Children yielded from iteration / properties keep their parent alive.

  Without parent keepalive the underlying libtsk handle can be freed
  while a yielded child is still in use, producing a use-after-free.
  These tests drop every visible reference to the parent and force a
  GC pass before touching the child.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def _yield_first_file(self):
    """Return a File yielded from iteration, with no caller-visible parent."""
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    directory = fs.open_dir('/')
    iterator = iter(directory)
    first = next(iterator)
    # Caller does not receive img / fs / directory / iterator; only the
    # File. The C-level keepalive must hold them alive.
    return first

  def testIteratedFileSurvivesParentDrop(self):
    """A File yielded by Directory iteration must outlive its FS_Info."""
    file_object = self._yield_first_file()
    # Force any cyclic collection now -- if our keepalive is wrong the
    # FS_Info / Img_Info would be reclaimed here.
    gc.collect()
    self.assertIsNotNone(file_object.info)
    if file_object.info.name:
      # Touching the borrowed name buffer reaches into FS-owned memory.
      self.assertIsNotNone(file_object.info.name.name)

  def testOpenedFileSurvivesParentDrop(self):
    """A File from FS_Info.open_meta must outlive its FS_Info."""
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    file_object = fs.open_meta(15)
    del fs
    del img
    gc.collect()
    # passwords.txt is 116 bytes at inode 15 in the fixture image.
    self.assertEqual(file_object.read_random(0, 16), b'place,user,passw')

  def testDirectoryFromOpenDirSurvivesParentDrop(self):
    """A Directory from FS_Info.open_dir must outlive its FS_Info."""
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    directory = fs.open_dir('/')
    del fs
    del img
    gc.collect()
    names = [entry.info.name.name
             for entry in directory if entry.info and entry.info.name]
    self.assertIn(b'passwords.txt', names)

  def testStructGetterSurvivesParentDrop(self):
    """A borrowed struct from a property getter must outlive its parent.

    file.info is a borrowed pyTSK_FS_FILE pointer into FS-owned memory.
    Releasing the File wrapper must not invalidate the borrowed view.
    """
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    file_object = fs.open_meta(15)
    info = file_object.info
    meta = info.meta
    del file_object
    del fs
    del img
    gc.collect()
    self.assertEqual(meta.size, 116)


class ConcurrentParentDropTest(unittest.TestCase):
  """One thread iterates while another drops the parent reference.

  This is the multi-threaded version of ParentKeepaliveTest. It only
  meaningfully races on free-threaded builds, but is harmless on the
  GIL build (just exercises the keepalive path under thread switches).
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testReadAfterParentDroppedOnOtherThread(self):
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    file_object = fs.open_meta(15)

    holder = {'fs': fs, 'img': img}

    def reader(_index):
      for _ in range(100):
        self.assertEqual(
            file_object.read_random(0, 16), b'place,user,passw')

    def dropper(_index):
      # Drop visible parents while the reader is mid-flight; the
      # file_object's python_object1 keepalive must keep the libtsk
      # handle alive until the file_object itself is released.
      holder.clear()
      gc.collect()

    barrier = threading.Barrier(2)
    errors = []

    def runner(target, index):
      try:
        barrier.wait()
        target(index)
      except BaseException as exc:  # pylint: disable=broad-except
        errors.append(exc)

    threads = [
        threading.Thread(target=runner, args=(reader, 0)),
        threading.Thread(target=runner, args=(dropper, 1)),
    ]
    for thread in threads:
      thread.start()
    for thread in threads:
      thread.join()
    if errors:
      raise errors[0]


class ConcurrentErrorPathTest(unittest.TestCase):
  """tsk_error_get must be per-thread under concurrent failures.

  When TSK_MULTITHREAD_LIB is missing libtsk falls back to a single
  global TSK_ERROR_INFO; concurrent failing calls then scramble each
  other's errno + errstr buffers. We trigger a known-bogus open in
  many threads at once and assert the resulting Python exception
  message is well-formed every time.
  """

  def testConcurrentInvalidOpens(self):
    img = pytsk3.Img_Info(url=_TEST_IMAGE)

    def worker(index):
      seen_errors = 0
      for _ in range(50):
        try:
          # Inode 19 does not exist in the fixture; this consistently
          # raises IOError and writes to libtsk's error buffer.
          fs = pytsk3.FS_Info(img, offset=0)
          fs.open_meta(19)
        except IOError as exc:
          seen_errors += 1
          # The string must be intact (no NUL truncation, no garbage)
          # even when other threads are racing the same error path.
          message = str(exc)
          self.assertTrue(message)
          self.assertNotIn('\x00', message)
      self.assertEqual(seen_errors, 50, f'thread {index} lost errors')

    _run_concurrently(worker, 8)


class ConcurrentVolumeInfoTest(unittest.TestCase):
  """Iterating Volume_Info from per-thread instances."""

  def setUp(self):
    self._test_file = _TEST_VOLUME

  def testIndependentVolumeInfos(self):

    def worker(_index):
      img = pytsk3.Img_Info(url=self._test_file)
      vs = pytsk3.Volume_Info(img)
      addrs = [part.addr for part in vs]
      return addrs

    results = _run_concurrently(worker, 8)
    self.assertTrue(all(r == results[0] for r in results))
    self.assertGreater(len(results[0]), 0)

  def testVolumePartSurvivesParentDrop(self):
    """Volume_Info.iternext yields TSK_VS_PART_INFO borrowed from the VS.

    With the parent keepalive, the part wrapper must remain valid
    after Volume_Info and Img_Info go out of scope.
    """
    img = pytsk3.Img_Info(url=self._test_file)
    vs = pytsk3.Volume_Info(img)
    parts = list(vs)
    del vs
    del img
    gc.collect()
    # Touching addr / start / len / desc reaches into VS-owned memory.
    for part in parts:
      _ = part.addr
      _ = part.start
      _ = part.len


class CloseDuringReadTest(unittest.TestCase):
  """Img_Info.close() while another thread is mid-read.

  Img_Info_read takes the per-instance state_lock around the
  img_is_open check and the actual tsk_img_read call; Img_Info_close
  takes the same lock while flipping img_is_open. As a result a
  close() call cannot tear state down mid-read, and any read started
  after close has flipped the flag observes a clean IOError.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testCloseConcurrentWithReader(self):
    img = pytsk3.Img_Info(url=self._test_file)
    stop = threading.Event()
    errors = []

    def reader():
      while not stop.is_set():
        try:
          # Either succeeds with the right bytes, or raises a clean
          # IOError once close() lands. Anything else (segfault,
          # garbage bytes) is a bug.
          data = img.read(0x5800, 16)
          if data:
            self.assertEqual(data, b'place,user,passw')
        except IOError:
          return  # post-close path
        except BaseException as exc:  # pylint: disable=broad-except
          errors.append(exc)
          return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
      thread.start()
    # Let readers spin up briefly, then close from this thread.
    threading.Event().wait(0.05)
    img.close()
    stop.set()
    for thread in threads:
      thread.join()
    if errors:
      raise errors[0]


class SharedFileConcurrentReadTest(unittest.TestCase):
  """One File handle hammered from many threads at different offsets.

  pytsk3 does not synchronize File.read_random itself; libtsk's FS
  cache_lock is what serializes the underlying read. This test
  exercises that path -- if libtsk's cache_lock were a no-op (the
  pre-fix state) the resulting bytes would scramble across threads.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testSharedFileReadRandom(self):
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    file_object = fs.open_meta(15)
    # Snapshot the full file once (uncontended) and use it as the
    # ground truth for every concurrent read below.
    expected = file_object.read_random(0, 116)
    self.assertEqual(len(expected), 116)

    def worker(_index):
      for _ in range(200):
        for off in (0, 16, 32, 48, 64, 80):
          chunk = file_object.read_random(off, 16)
          self.assertEqual(chunk, expected[off:off + 16])

    _run_concurrently(worker, 8)


class RecursiveWalkStressTest(unittest.TestCase):
  """Recursive directory walks under many threads, each on its own FS.

  This is the soak test: long-running concurrent allocation churn
  exercises every yield path through new_class_wrapper +
  StructWrapper.assign + dealloc. A regression in the parent
  keepalive (extra Py_IncRef without matching DecRef, or vice versa)
  would surface as a steady leak; a refcount asymmetry surfaces as
  an immediate crash.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def _walk(self, fs, directory, depth=0):
    count = 0
    if depth > 8:
      return count
    for entry in directory:
      count += 1
      if not entry.info or not entry.info.name:
        continue
      name = entry.info.name.name
      if name in (b'.', b'..'):
        continue
      if not entry.info.meta:
        continue
      meta_type = entry.info.meta.type
      if meta_type == pytsk3.TSK_FS_META_TYPE_DIR:
        try:
          sub = entry.as_directory()
        except IOError:
          continue
        count += self._walk(fs, sub, depth + 1)
    return count

  def testRecursiveWalkStress(self):

    def worker(_index):
      img = pytsk3.Img_Info(url=self._test_file)
      fs = pytsk3.FS_Info(img, offset=0)
      total = 0
      for _ in range(20):
        directory = fs.open_dir('/')
        total += self._walk(fs, directory)
      return total

    results = _run_concurrently(worker, 8)
    # Every thread must have visited the same number of entries.
    self.assertTrue(all(r == results[0] for r in results), results)
    self.assertGreater(results[0], 0)


class GcUnderLoadTest(unittest.TestCase):
  """Force GC in a hot loop while workers iterate.

  Cyclic GC visits all tracked objects and may run __del__ /
  tp_dealloc on things that became unreachable since the last
  collection. A bug in our parent keepalive (e.g. forgetting to
  Py_IncRef in new_class_wrapper) would surface here as a UAF when
  GC reaps a parent the worker is still using.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testGcConcurrentWithIteration(self):
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    stop = threading.Event()
    errors = []

    def gc_worker():
      while not stop.is_set():
        gc.collect()

    def iter_worker(_index):
      try:
        for _ in range(100):
          directory = fs.open_dir('/')
          names = []
          for entry in directory:
            if entry.info and entry.info.name:
              names.append(entry.info.name.name)
          self.assertIn(b'passwords.txt', names)
      except BaseException as exc:  # pylint: disable=broad-except
        errors.append(exc)

    gc_thread = threading.Thread(target=gc_worker)
    gc_thread.start()
    try:
      _run_concurrently(iter_worker, 4)
    finally:
      stop.set()
      gc_thread.join()
    if errors:
      raise errors[0]


class GilStaysOffTest(unittest.TestCase):
  """sys._is_gil_enabled() must remain False across pytsk3 operations.

  testModuleDoesNotForceGil only checks the post-import state. A
  bug that re-enables the GIL on a specific code path (e.g. an
  unguarded private API call) wouldn't be caught there. Hammer a
  representative mix of pytsk3 operations and confirm the GIL
  stays off the entire time.
  """

  @unittest.skipUnless(
      _is_free_threaded(),
      'requires a free-threaded Python build')
  def testGilStaysOffAcrossOperations(self):
    self.assertFalse(sys._is_gil_enabled())
    img = pytsk3.Img_Info(url=_TEST_IMAGE)
    self.assertFalse(sys._is_gil_enabled())
    fs = pytsk3.FS_Info(img, offset=0)
    self.assertFalse(sys._is_gil_enabled())
    directory = fs.open_dir('/')
    self.assertFalse(sys._is_gil_enabled())
    for entry in directory:
      if entry.info and entry.info.meta:
        _ = entry.info.meta.size
    self.assertFalse(sys._is_gil_enabled())
    file_object = fs.open_meta(15)
    self.assertEqual(file_object.read_random(0, 16), b'place,user,passw')
    self.assertFalse(sys._is_gil_enabled())
    img.close()
    self.assertFalse(sys._is_gil_enabled())


class IteratorCursorThreadSafetyTest(unittest.TestCase):
  """Sharing one Directory iterator across threads should be safe.

  Before the per-instance iter_lock was introduced, two threads
  iterating the same Directory would race on self->current and
  produce skipped/duplicated entries. With iter_lock each entry
  index is consumed exactly once across all threads, so the union
  of yields is the full directory listing.
  """

  def setUp(self):
    self._test_file = _TEST_IMAGE

  def testSharedDirectoryIterator(self):
    img = pytsk3.Img_Info(url=self._test_file)
    fs = pytsk3.FS_Info(img, offset=0)
    directory = fs.open_dir('/')

    # Build a baseline: how many entries are in /. Use a fresh
    # Directory so the shared one below starts at cursor 0 (the C
    # constructor sets current = 0; we deliberately do not call iter()
    # here because that would also reset).
    baseline = sum(1 for _ in fs.open_dir('/'))

    yielded = []
    yielded_lock = threading.Lock()

    def worker(_index):
      # Note: do NOT call iter(directory) here. Directory is its own
      # iterator and __iter__ resets the cursor under iter_lock --
      # which is correct behavior for "for x in d:" in a single
      # thread, but would defeat the test that all workers consume
      # from the same cursor sequence.
      while True:
        try:
          entry = directory.__next__()
        except StopIteration:
          return
        with yielded_lock:
          yielded.append(entry)

    _run_concurrently(worker, 4)
    # Cursor was advanced exactly baseline times across all workers.
    # An off-by-one (missed lock release, double-advance) would change
    # this count; a true race (skipping the cap-at-INT_MAX check)
    # could overshoot indefinitely.
    self.assertEqual(len(yielded), baseline)


def _have_subinterpreters():
  """True when the public test_support.interpreters API is available."""
  try:
    import test.support.interpreters  # noqa: F401
    return True
  except ImportError:
    pass
  try:
    import _interpreters  # noqa: F401
    return True
  except ImportError:
    return False


_SUBINTERP_SCRIPT = (
    'import pytsk3\n'
    'img = pytsk3.Img_Info(url=' + repr(_TEST_IMAGE) + ')\n'
    'assert img.get_size() == 102400\n'
    'fs = pytsk3.FS_Info(img, offset=0)\n'
    'f = fs.open_meta(15)\n'
    "assert f.read_random(0, 16) == b'place,user,passw'\n")


class SubinterpreterImportTest(unittest.TestCase):
  """pytsk3 must initialize cleanly inside a subinterpreter.

  tsk_init() is wrapped in std::call_once so the C class templates
  are only initialized once across all interpreters. Importing
  pytsk3 in a fresh subinterpreter exercises that path and surfaces
  any cross-subinterpreter state leak.

  The subinterpreter API has shifted across Python versions:
    * 3.11: only the private `_xxsubinterpreters` module, with a
      `.run_string(id, script)` signature.
    * 3.12-3.13: `test.support.interpreters` available but the
      Interpreter object exposes `.run(script)`, not `.exec(...)`.
    * 3.14+: `interp.exec(script)` is the documented method.
  This test probes each API in turn and skips when none works.
  """

  @unittest.skipUnless(_have_subinterpreters(),
                       'subinterpreter API not available')
  def testImportInSubinterpreter(self):
    # Try the public API first.
    try:
      from test.support import interpreters  # type: ignore
    except ImportError:
      interpreters = None  # pylint: disable=invalid-name

    if interpreters is not None:
      interp = interpreters.create()
      try:
        runner = getattr(interp, 'exec', None) or getattr(interp, 'run', None)
        if runner is None:
          self.skipTest(
              'test.support.interpreters has no exec/run on this build')
        runner(_SUBINTERP_SCRIPT)
        return
      finally:
        close = getattr(interp, 'close', None)
        if close is not None:
          close()

    # Fall back to the private API. The module name and run_string
    # signature both vary across versions; tolerate either.
    try:
      import _interpreters  # type: ignore  # noqa: F401
      private = _interpreters
    except ImportError:
      try:
        import _xxsubinterpreters  # type: ignore  # noqa: F401
        private = _xxsubinterpreters
      except ImportError:
        self.skipTest('no usable subinterpreter API')

    interp_id = private.create()
    try:
      run_string = getattr(private, 'run_string', None)
      if run_string is None:
        self.skipTest('private subinterpreter API has no run_string')
      run_string(interp_id, _SUBINTERP_SCRIPT)
    finally:
      private.destroy(interp_id)


if __name__ == '__main__':
  unittest.main()
