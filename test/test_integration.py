# (c) 2020 Michał Górny
# 2-clause BSD license

""" Integration tests. """

import datetime
import io
import shutil
import subprocess
import tempfile
import typing
import unittest

from pathlib import Path
from unittest.mock import MagicMock, patch

import freezegun

import pkgcore.ebuild.ebuild_src
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.util import parserestrict

from nattka.bugzilla import BugCategory
from nattka.cli import main, have_nattka_depgraph

from test.test_bugzilla import makebug
from test.test_package import get_test_repo


FULL_CC = ['alpha@gentoo.org', 'amd64-linux@gentoo.org',
           'amd64@gentoo.org', 'hppa@gentoo.org',
           'sparc-freebsd@gentoo.org', 'x86-macos@gentoo.org']


class IntegrationTestCase(unittest.TestCase):
    """
    A test case for an integration test.  Combines Bugzilla support
    with a temporary clone of the repository.
    """

    tempdir: tempfile.TemporaryDirectory
    repo: UnconfiguredTree
    common_args: typing.List[str]

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        tempdir_path = Path(self.tempdir.name)
        self.cache_file = str(tempdir_path / 'cache.json')
        basedir = Path(__file__).parent
        for subdir in ('conf', 'data'):
            shutil.copytree(basedir / subdir,
                            tempdir_path / subdir,
                            symlinks=True)

        self.repo = get_test_repo(tempdir_path).repo

        self.common_args = [
            # we do not need an API key since we mock NattkaBugzilla
            # but the program refuses to run without it
            '--api-key', 'UNUSED',
            '--portage-conf', str(tempdir_path / 'conf'),
            '--repo', self.repo.location,
        ]

        assert subprocess.Popen(['git', 'init'],
                                cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(['git', 'add', '-A'],
                                cwd=self.repo.location).wait() == 0

    def tearDown(self):
        self.tempdir.cleanup()

    def get_package(self,
                    atom: str
                    ) -> pkgcore.ebuild.ebuild_src.package:
        pkg = self.repo.match(parserestrict.parse_match(atom))
        assert len(pkg) == 1
        return pkg[0]


class IntegrationNoActionTests(IntegrationTestCase):
    """Test cases for bugs that can not be processed"""

    reset_msg = ('Resetting sanity check; package list is empty '
                 'or all packages are done.')

    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            '   \r\n'
                            '\r\n',
                            sanity_check=initial_status),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_empty_package_list(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        add_keywords.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_empty_package_list(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reset_n(self, bugz, add_keywords):
        """
        Test skipping a bug that needs sanity-check reset, with '-n'.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reset(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, None, self.reset_msg)

    def empty_keywords_preset(self,
                              bugz: MagicMock
                              ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n'
                            'test/alpha-amd64-hppa-testing-2\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_empty_keywords(self, bugz, add_keywords):
        bugz_inst = self.empty_keywords_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        add_keywords.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_empty_keywords(self, bugz, add_keywords):
        bugz_inst = self.empty_keywords_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, None, 'Resetting sanity check; keywords are not '
            'fully specified and arches are not CC-ed.')

    def wrong_category_preset(self,
                              bugz: MagicMock
                              ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(None, ''),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.cli.match_package_list')
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_wrong_category(self, bugz, match_package_list):
        bugz_inst = self.wrong_category_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        match_package_list.assert_not_called()

    @patch('nattka.cli.match_package_list')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_wrong_category(self, bugz, match_package_list):
        bugz_inst = self.wrong_category_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        match_package_list.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_finished_package_list(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ, '''
                test/amd64-stable-1 amd64
            ''', sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_finished_package_no_keywords(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ, '''
                test/amd64-stable-1
            ''', sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()


class IntegrationSuccessTests(IntegrationTestCase):
    """Integration tests that pass sanity-check"""

    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None,
                   **kwargs
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n'
                            'test/alpha-amd64-hppa-testing-2 amd64 hppa\r\n',
                            sanity_check=initial_status,
                            **kwargs),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    def post_verify(self):
        """Verify that the original data has been restored"""
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', '~amd64', '~hppa'))

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_stablereq(self, bugz, sout):
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', 'amd64', 'hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/amd64-testing-1 ~amd64
=test/alpha-amd64-hppa-testing-2 ~amd64 ~hppa''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_keywordreq(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 alpha ~hppa\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~alpha', '~amd64', '~hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (KEYWORDREQ)
=test/amd64-testing-1 **  # -> ~alpha ~hppa''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_n(self, bugz, sout):
        """Test apply with '-n' option."""
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '-n', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', '~amd64', '~hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/amd64-testing-1 ~amd64
=test/alpha-amd64-hppa-testing-2 ~amd64 ~hppa''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_filter_arch(self, bugz, sout):
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['amd64@gentoo.org'])

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', 'amd64', '~hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/amd64-testing-1 ~amd64
=test/alpha-amd64-hppa-testing-2 ~amd64''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_filter_host_arch(self, bugz, sout):
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['apply', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['hppa@gentoo.org'])

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', '~amd64', 'hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/alpha-amd64-hppa-testing-2 ~hppa''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_filter_arch_to_empty(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 hppa\r\n'
                            'test/alpha-amd64-hppa-testing-2 hppa\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['amd64@gentoo.org'])
        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322: no packages match requested arch''')

    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_skip_sanity_check(self, bugz):
        """Test that apply skips bug with failing sanity check"""
        bugz_inst = self.bug_preset(bugz, False)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', '~amd64', '~hppa'))

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_ignore_sanity_check(self, bugz, sout):
        """Test that apply --ignore-sanity-check works"""
        bugz_inst = self.bug_preset(bugz, False)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322',
                                     '--ignore-sanity-check']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', 'amd64', 'hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/amd64-testing-1 ~amd64
=test/alpha-amd64-hppa-testing-2 ~amd64 ~hppa''')

    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_depend_unresolved(self, bugz):
        """Test that apply skips bug with unresolved dependencies"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        bugz_inst.resolve_dependencies.assert_called()

        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_depend_resolved(self, bugz, sout):
        """Test that apply does not block on resolved dependencies"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322], resolved=True),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        bugz_inst.resolve_dependencies.assert_called()

        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~alpha', '~amd64'))
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (KEYWORDREQ)
=test/amd64-testing-deps-1 **  # -> ~alpha''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_depend_empty(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha ~hppa\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            '',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'hppa', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['hppa@gentoo.org'])
        bugz_inst.resolve_dependencies.assert_called()

        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64', '~hppa'))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (KEYWORDREQ)
=test/amd64-testing-deps-1 **  # -> ~hppa''')
    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_depend_irrelevant(self, bugz, sout):
        """Test that apply does not block on deps for other arches"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha ~hppa\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'hppa', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['hppa@gentoo.org'])
        bugz_inst.resolve_dependencies.assert_called()

        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64', '~hppa'))
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (KEYWORDREQ)
=test/amd64-testing-deps-1 **  # -> ~hppa''')

    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_depend_ignore(self, bugz, sout):
        """Test that apply --ignore-dependencies works"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322',
                                     '--ignore-dependencies']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        bugz_inst.resolve_dependencies.assert_called()

        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~alpha', '~amd64'))
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (KEYWORDREQ)
=test/amd64-testing-deps-1 **  # -> ~alpha''')

    @unittest.skipIf(not have_nattka_depgraph,
                     'networkx required for dep sorting')
    @patch('nattka.cli.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.cli.NattkaBugzilla')
    def test_apply_dep_sorting(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-deps-1 amd64\r\n'
                            'test/amd64-testing-1 amd64\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '-n', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/amd64-testing-1 ~amd64
=test/amd64-testing-deps-1 ~amd64''')

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_n(self, bugz):
        """Test processing with '-n'"""
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_none(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(560322, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_success(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_failure(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, 'All sanity-check issues have been resolved')
        self.post_verify()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()
        bugz_inst.update_status.assert_not_called()

        add_keywords.reset_mock()
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_expired(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        last_check = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        with freezegun.freeze_time(last_check):
            self.assertEqual(
                main(self.common_args + ['sanity-check', '--update-bugs',
                                         '560322', '--cache-file',
                                         self.cache_file]),
                0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_plist_changed(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_keywords_from_cc(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_keywords_from_cc_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org'],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_depend(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_depend_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_dependent_bug_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        bugz_inst.resolve_dependencies.return_value.update({
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha ~hppa\r\n',
                            blocks=[560322]),
        })
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_result_changed(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

        add_keywords.reset_mock()
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache_from_noupdate(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        self.assertEqual(
            main(self.common_args + ['sanity-check',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()
        bugz_inst.update_status.assert_not_called()

        add_keywords.reset_mock()
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()
        bugz_inst.update_status.assert_called()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_specified(self, bugz):
        """
        Test for depending on another bug when both bugs are listed
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560311', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560311, 560322])
        self.assertEqual(bugz_inst.update_status.call_count, 2)
        bugz_inst.update_status.assert_has_calls(
            [unittest.mock.call(560311, True, None),
             unittest.mock.call(560322, True, None)])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_auto(self, bugz):
        """
        Test for depending on another bug with autofetching
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_called()
        self.assertEqual(bugz_inst.update_status.call_count, 1)
        bugz_inst.update_status.assert_called_with(560322, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_failing(self, bugz):
        """
        Test that dependent sanity-check failure is not reported
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/mixed-keywords-4 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_called()
        self.assertEqual(bugz_inst.update_status.call_count, 1)
        bugz_inst.update_status.assert_called_with(560322, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_no_fetch_deps(self, bugz):
        """
        Test for depending on another bug with --no-fetch-dependencies
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311]),
        }
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--no-fetch-dependencies',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_not_called()
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_keywordreq_relaxed_syntax(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing alpha\r\n',
                            sanity_check=None),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(560322, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_keywords_above(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n'
                            'test/amd64-testing-1 ^\r\n',
                            ),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560311']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560311])
        bugz_inst.update_status.assert_called_with(
            560311, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_keywords_asterisk(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: makebug(BugCategory.STABLEREQ,
                            'test/amd64-stable-deps-10 amd64\r\n'
                            'test/amd64-stable-10 *\r\n'
                            # this one's irrelevant but we have dirty
                            # depgraph
                            'test/amd64-testing-1 amd64\r\n',
                            cc=['amd64@gentoo.org']
                            ),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560311']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560311])
        bugz_inst.update_status.assert_called_with(
            560311, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_keywords_partial_cc_match(self, bugz):
        """Test package list where some of the packages do not match CC"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64 hppa\r\n'
                            'test/amd64-testing-2 amd64\r\n',
                            cc=['hppa@gentoo.org']
                            ),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560311']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560311])
        bugz_inst.update_status.assert_called_with(
            560311, True, None)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cc_from_none(self, bugz):
        bugz_inst = self.bug_preset(bugz, keywords=['CC-ARCHES'])
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            cc_add=['amd64@gentoo.org', 'hppa@gentoo.org'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cc_from_success(self, bugz):
        bugz_inst = self.bug_preset(bugz,
                                    keywords=['CC-ARCHES'],
                                    initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            cc_add=['amd64@gentoo.org', 'hppa@gentoo.org'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cc_from_success_cache(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=None)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--cache-file', self.cache_file,
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None)
        self.post_verify()

        bugz_inst = self.bug_preset(bugz,
                                    keywords=['CC-ARCHES'],
                                    initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--cache-file', self.cache_file,
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            cc_add=['amd64@gentoo.org', 'hppa@gentoo.org'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cc_prefix(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 amd64 hppa amd64-linux '
                            'x86-macos sparc-freebsd\r\n',
                            keywords=['CC-ARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            cc_add=['hppa@gentoo.org'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_allarches_add(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-stable-hppa-testing-1 hppa\r\n'),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            keywords_add=['ALLARCHES'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_allarches_remove(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            keywords=['ALLARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            keywords_remove=['ALLARCHES'])
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_commit(self, bugz):
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=self.repo.location).wait() == 0

        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            0)
        self.assertEqual(
            main(self.common_args + ['commit', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%s',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/alpha-amd64-hppa-testing: Stabilize 2 amd64 hppa, #560322

test/alpha-amd64-hppa-testing/alpha-amd64-hppa-testing-2.ebuild
test
test@example.com
test/amd64-testing: Stabilize 1 amd64, #560322

test/amd64-testing/amd64-testing-1.ebuild
''')

    @unittest.skipIf(not have_nattka_depgraph,
                     'networkx required for dep sorting')
    @patch('nattka.cli.NattkaBugzilla')
    def test_commit_dep_sorting(self, bugz):
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=self.repo.location).wait() == 0

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/amd64-testing-deps-1 amd64\r\n'
                            'test/amd64-testing-1 amd64\r\n',
                            sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            0)
        self.assertEqual(
            main(self.common_args + ['commit', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%s',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/amd64-testing-deps: Stabilize 1 amd64, #560322

test/amd64-testing-deps/amd64-testing-deps-1.ebuild
test
test@example.com
test/amd64-testing: Stabilize 1 amd64, #560322

test/amd64-testing/amd64-testing-1.ebuild
''')


class IntegrationFailureTests(IntegrationTestCase):
    """Integration tests that fail sanity-check"""

    fail_msg = ('Sanity check failed:\n\n'
                '> test/amd64-testing-deps-1\n'
                '>   rdepend ~alpha stable profile alpha (1 total)\n'
                '>     test/amd64-testing')

    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None,
                   **kwargs
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=initial_status,
                            **kwargs),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    def post_verify(self) -> None:
        """Verify that the original data has been restored"""
        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64',))

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_n(self, bugz):
        """Test processing with -n"""
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_none(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_fail_no_comment(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        bugz_inst.get_latest_comment.return_value = None
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_fail_other(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = (
            'Sanity check failed:\n\n> nonsolvable depset(rdepend) '
            'keyword(~alpha) stable profile (alpha) (1 total): '
            'solutions: [ test/frobnicate ]')
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_fail(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = self.fail_msg
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_from_success(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cache(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called()

        with patch('nattka.cli.add_keywords') as add_keywords:
            bugz_inst = self.bug_preset(bugz, initial_status=False)
            bugz_inst.update_status.reset_mock()
            self.assertEqual(
                main(self.common_args + ['sanity-check', '--update-bugs',
                                         '560322', '--cache-file',
                                         self.cache_file]),
                0)
            bugz_inst.find_bugs.assert_called_with(bugs=[560322])
            add_keywords.assert_not_called()
            bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reason_malformed_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            '<>amd64-testing-deps-1 ~alpha\r\n'),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> invalid '
            'package spec: <>amd64-testing-deps-1')

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reason_malformed_plist_cache_empty_reported(
            self, bugz, add_keywords):
        """
        Regression test for reporting an exception-failure when cache
        is used and previous comment matches
        """
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            '<>amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=False),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        bugz_inst.get_latest_comment.return_value = (
            'Unable to check for sanity:\n\n> invalid package spec: '
            '<>amd64-testing-deps-1')
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--cache-file', self.cache_file,
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reason_disallowed_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            '>=test/amd64-testing-deps-1 ~alpha\r\n'),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> disallowed '
            'package spec (only = allowed): >=test/amd64-testing-deps-1')

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reason_non_matched_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n'),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> no match '
            'for package: test/enoent-7')

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_reason_non_matched_keywords(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 amd64 ~mysuperarch\r\n'),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> incorrect '
            'keywords: mysuperarch')

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_invalid(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_called()
        self.assertEqual(bugz_inst.update_status.call_count, 1)
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n'
                           '> dependent bug #560311 has errors')
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_and_bug_invalid(self, bugz):
        """Verify that issues with current bug take precedence over deps"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/enoent-1 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_called()
        self.assertEqual(bugz_inst.update_status.call_count, 1)
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n'
                           '> no match for package: test/enoent-1')
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_depend_missing_keywords(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311]),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: makebug(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1',
                            blocks=[560322]),
        }
        bugz_inst.resolve_dependencies.return_value.update(
            bugz_inst.find_bugs.return_value)

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_dependencies.assert_called()
        self.assertEqual(bugz_inst.update_status.call_count, 1)
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n'
                           '> dependent bug #560311 is missing keywords')
        self.post_verify()

    @patch('nattka.cli.NattkaBugzilla')
    def test_sanity_cc(self, bugz):
        bugz_inst = self.bug_preset(bugz, keywords=['CC-ARCHES'])
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)
        self.post_verify()


class IntegrationLimiterTests(IntegrationTestCase):
    """
    Tests for limiting the number of processed bugs.
    """

    def bug_preset(self,
                   bugz: MagicMock
                   ) -> MagicMock:
        bugs = {}
        for i in range(10):
            bugs[100000 + i] = makebug(BugCategory.STABLEREQ,
                                       'test/amd64-testing-1 amd64\r\n')

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = bugs
        bugz_inst.resolve_dependencies.return_value = bugs
        return bugz_inst

    @patch('nattka.cli.NattkaBugzilla')
    def test_bug_limit(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--bug-limit', '5']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            unresolved=True,
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            skip_tags=['nattka:skip'])
        self.assertEqual(bugz_inst.update_status.call_count, 5)
        bugz_inst.update_status.assert_has_calls(
            [unittest.mock.call(100009, True, None),
             unittest.mock.call(100008, True, None),
             unittest.mock.call(100007, True, None),
             unittest.mock.call(100006, True, None),
             unittest.mock.call(100005, True, None)])


class SearchFilterTests(IntegrationTestCase):
    """
    Tests for passing search filters over to find_bugs().
    """

    @patch('nattka.cli.NattkaBugzilla')
    def test_default(self, bugz):
        """Verify default search filters"""
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ])

    @patch('nattka.cli.NattkaBugzilla')
    def test_keywordreq(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--keywordreq']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.KEYWORDREQ])

    @patch('nattka.cli.NattkaBugzilla')
    def test_stablereq(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--stablereq']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.STABLEREQ])

    @patch('nattka.cli.NattkaBugzilla')
    def test_keywordreq_and_stablereq(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--keywordreq',
                                     '--stablereq']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ])

    @patch('nattka.cli.NattkaBugzilla')
    def test_security(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--security']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            security=True)


class ResolveTests(IntegrationTestCase):
    """Tests for resolve command"""

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_one_of_many(self, bugz):
        """Test resolve with one of many arches done"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', 'hppa', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322, ['hppa@gentoo.org'], 'hppa done', False)

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_all_of_many(self, bugz):
        """Test resolve with all of many arches done"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322,
            ['amd64@gentoo.org', 'hppa@gentoo.org'],
            'amd64 hppa done\n\nall arches done',
            True)

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_security(self, bugz):
        """Test that security bugs are not closed"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            security=True),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322,
            ['amd64@gentoo.org', 'hppa@gentoo.org'],
            'amd64 hppa done\n\nall arches done',
            False)

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_closed(self, bugz):
        """Test that closed bugs do not get their resolution changed"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            resolved=True),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322,
            ['amd64@gentoo.org', 'hppa@gentoo.org'],
            'amd64 hppa done\n\nall arches done',
            False)

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_no_resolve(self, bugz):
        """Test that --no-resolve inhibits resolving bugs"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322',
                                     '--no-resolve']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322,
            ['amd64@gentoo.org', 'hppa@gentoo.org'],
            'amd64 hppa done\n\nall arches done',
            False)

    @patch('nattka.cli.NattkaBugzilla')
    def test_resolve_pretend(self, bugz):
        """Test that --pretend inhibits updates"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: makebug(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322',
                                     '--pretend']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_not_called()
