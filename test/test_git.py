# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for git support. """

import os
import subprocess
import tempfile
import unittest

from pathlib import Path

from nattka.git import (git_get_toplevel, git_is_dirty, git_commit,
                        git_reset_changes, GitDirtyWorkTree,
                        GitWorkTree)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_git_get_toplevel(self):
        """ Check whether git_get_toplevel() works correctly. """
        td = Path(self.tempdir.name)

        # should return None or find some containing repository
        self.assertNotEqual(git_get_toplevel(Path(self.tempdir.name)),
                            td)

        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        self.assertEqual(git_get_toplevel(td), td)

        sd = td / 'subdir'
        os.mkdir(sd)
        self.assertEqual(git_get_toplevel(sd), td)

    def test_git_is_dirty(self):
        """ Test whether we detect dirty working tree correctly. """
        td = Path(self.tempdir.name)

        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        self.assertFalse(git_is_dirty(td))

        with open(td / 'file', 'w') as f:
            f.write('test\n')
        assert (subprocess.Popen(['git', 'add', '-N', 'file'], cwd=td)
                          .wait() == 0)
        self.assertTrue(git_is_dirty(td))

        assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                          .wait() == 0)
        self.assertFalse(git_is_dirty(td))

    def test_git_commit(self):
        """Test whether we commit correctly"""
        td = Path(self.tempdir.name)
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=td).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=td).wait() == 0
        with open(td / 'file', 'w') as f:
            f.write('test\n')
            f.flush()

        assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                          .wait() == 0)
        self.assertNotEqual(git_commit(td, 'test commit', ['file']), '')
        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%s',
                              '--name-only', '-1'],
                             cwd=td,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test commit

file
''')

    def test_git_commit_no_changes(self):
        """Test whether we fail commit on no changes"""
        td = Path(self.tempdir.name)
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=td).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=td).wait() == 0
        with open(td / 'file', 'w') as f:
            f.write('test\n')
            f.flush()

        assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                          .wait() == 0)
        git_commit(td, 'test commit', ['file'])
        self.assertRaises(
            RuntimeError,
            git_commit, td, 'second attempted commit', ['file'])

    def test_git_reset_changes(self):
        """ Test whether we reset changes correctly. """
        td = Path(self.tempdir.name)
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(td / 'file', 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                              .wait() == 0)
            f.write('second\n')

        git_reset_changes(td)
        with open(td / 'file', 'r') as f:
            self.assertEqual(f.read(), 'test\n')

    def test_context_manager(self):
        td = Path(self.tempdir.name)
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(td / 'file', 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', 'file'], cwd=td)
                              .wait() == 0)

            with GitWorkTree(td):
                f.write('second\n')
                f.flush()

        with open(td / 'file', 'r') as f:
            self.assertEqual(f.read(), 'test\n')

    def test_context_manager_dirty(self):
        td = Path(self.tempdir.name)
        assert subprocess.Popen(['git', 'init'], cwd=td).wait() == 0
        with open(td / 'file', 'w') as f:
            f.write('test\n')
            f.flush()
            assert (subprocess.Popen(['git', 'add', '-N', 'file'], cwd=td)
                              .wait() == 0)

            with self.assertRaises(GitDirtyWorkTree):
                with GitWorkTree(td):
                    pass
