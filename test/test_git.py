""" Tests for git support. """

import os
import os.path
import subprocess
import tempfile
import unittest

from nattka.git import (git_get_toplevel, git_is_dirty,
                        git_reset_changes, GitDirtyWorkTree,
                        GitWorkTree)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_git_get_toplevel(self):
        """ Check whether git_get_toplevel() works correctly. """
        td = self.tempdir.name

        # should return None or find some containing repository
        self.assertNotEqual(git_get_toplevel(self.tempdir.name), td)

        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        self.assertEqual(git_get_toplevel(td), td)

        sd = os.path.join(td, 'subdir')
        os.mkdir(sd)
        self.assertEqual(git_get_toplevel(sd), td)

    def test_git_is_dirty(self):
        """ Test whether we detect dirty working tree correctly. """
        td = self.tempdir.name

        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        self.assertFalse(git_is_dirty(td))

        with open(os.path.join(td, 'file'), 'w') as f:
            f.write('test\n')
        assert (subprocess.Popen(['git', 'add', '-N', 'file'], cwd=td)
                          .wait() == 0)
        self.assertTrue(git_is_dirty(td))

        assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                          .wait() == 0)
        self.assertFalse(git_is_dirty(td))

    def test_git_reset_changes(self):
        """ Test whether we reset changes correctly. """
        td = self.tempdir.name
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(os.path.join(td, 'file'), 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                              .wait() == 0)
            f.write('second\n')

        git_reset_changes(td)
        with open(os.path.join(td, 'file'), 'r') as f:
            self.assertEqual(f.read(), 'test\n')

    def test_context_manager(self):
        td = self.tempdir.name
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(os.path.join(td, 'file'), 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                              .wait() == 0)

            with GitWorkTree(td) as wt:
                f.write('second\n')
                f.flush()

        with open(os.path.join(td, 'file'), 'r') as f:
            self.assertEqual(f.read(), 'test\n')

    def test_context_manager_dirty(self):
        td = self.tempdir.name
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(os.path.join(td, 'file'), 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', '-N', 'file'], cwd=td)
                              .wait() == 0)

            with self.assertRaises(GitDirtyWorkTree):
                with GitWorkTree(td) as wt:
                    pass
