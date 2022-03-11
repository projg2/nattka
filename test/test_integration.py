# (c) 2020-2021 Michał Górny
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

import pkgcore.ebuild.ebuild_src
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.util import parserestrict

from nattka.bugzilla import BugCategory, BugInfo
from nattka.__main__ import main, have_nattka_depgraph

from test.test_package import get_test_repo


FULL_CC = ['alpha@gentoo.org', 'amd64-linux@gentoo.org',
           'amd64@gentoo.org', 'hppa@gentoo.org',
           'sparc-freebsd@gentoo.org', 'x86-macos@gentoo.org']


class FakeDateTime:
    def __init__(self, dt):
        self._dt = dt

    def utcnow(self):
        return self._dt


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
            560322: BugInfo(BugCategory.STABLEREQ,
                            '   \r\n'
                            '\r\n',
                            sanity_check=initial_status,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_empty_package_list(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        add_keywords.assert_not_called()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_empty_package_list(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 hppa\r\n'
                            'test/alpha-amd64-hppa-testing-2\r\n',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_empty_keywords(self, bugz, add_keywords):
        bugz_inst = self.empty_keywords_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        add_keywords.assert_not_called()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_empty_keywords(self, bugz, add_keywords):
        bugz_inst = self.empty_keywords_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, None, 'Keywords are not fully specified and arches '
            'are not CC-ed for the following packages:\n\n'
            '- =test/alpha-amd64-hppa-testing-2')

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_empty_keywords_cc_arches(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3\r\n'
                            'test/amd64-testing-1 amd64\r\n',
                            keywords=['CC-ARCHES'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            560322, None, 'Keywords are not fully specified and arches '
            'are not CC-ed for the following packages:\n\n'
            '- =test/mixed-keywords-3')

    def wrong_category_preset(self,
                              bugz: MagicMock
                              ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(None, '',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        return bugz_inst

    @patch('nattka.__main__.match_package_list')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_wrong_category(self, bugz, match_package_list):
        bugz_inst = self.wrong_category_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', '*', '560322']),
            1)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=FULL_CC)
        match_package_list.assert_not_called()

    @patch('nattka.__main__.match_package_list')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_wrong_category(self, bugz, match_package_list):
        bugz_inst = self.wrong_category_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        match_package_list.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_finished_package_list(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-stable-1 amd64',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_finished_package_no_keywords(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-stable-1',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
                   last_change_time: datetime.datetime = datetime.datetime(
                       2020, 1, 1, 12, 0, 0),
                   **kwargs
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n'
                            'test/alpha-amd64-hppa-testing-2 amd64 hppa\r\n',
                            sanity_check=initial_status,
                            last_change_time=last_change_time,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_keywordreq(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_filter_arch_to_empty(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_depend_unresolved(self, bugz):
        """Test that apply skips bug with unresolved dependencies"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_depend_resolved(self, bugz, sout):
        """Test that apply does not block on resolved dependencies"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_depend_empty(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha ~hppa\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_depend_irrelevant(self, bugz, sout):
        """Test that apply does not block on deps for other arches"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha ~hppa\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_depend_ignore(self, bugz, sout):
        """Test that apply --ignore-dependencies works"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311], sanity_check=True),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
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
    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_dep_sorting(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_allarches(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 amd64 hppa\r\n'
                            'test/mixed-keywords-4 amd64 hppa\r\n',
                            sanity_check=True,
                            keywords=['ALLARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['amd64@gentoo.org'])

        self.assertEqual(
            self.get_package('=test/mixed-keywords-3').keywords,
            ('~alpha', 'amd64', 'hppa'))
        self.assertEqual(
            self.get_package('=test/mixed-keywords-4').keywords,
            ('amd64',))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ) ALLARCHES
=test/mixed-keywords-3 ~amd64 ~hppa
=test/mixed-keywords-4 ~amd64''')

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    @patch('nattka.__main__.NattkaBugzilla')
    def test_apply_allarches_ignore(self, bugz, sout):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 amd64 hppa\r\n'
                            'test/mixed-keywords-4 amd64 hppa\r\n',
                            sanity_check=True,
                            keywords=['ALLARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322',
                                     '--ignore-allarches']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            bugs=[560322],
            cc=['amd64@gentoo.org'])

        self.assertEqual(
            self.get_package('=test/mixed-keywords-3').keywords,
            ('~alpha', 'amd64', '~hppa'))
        self.assertEqual(
            self.get_package('=test/mixed-keywords-4').keywords,
            ('amd64',))

        self.assertEqual(
            sout.getvalue().strip(),
            '''# bug 560322 (STABLEREQ)
=test/mixed-keywords-3 ~amd64
=test/mixed-keywords-4 ~amd64''')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_n(self, bugz):
        """Test processing with '-n'"""
        bugz_inst = self.bug_preset(bugz, True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_from_none(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(560322, True, None)
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_from_success(self, bugz):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_expired(self, bugz, add_keywords):
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        last_check = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        with patch('nattka.__main__.datetime.datetime') as mocked_dt:
            mocked_dt.utcnow.return_value = last_check
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_keywords_from_cc(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_keywords_from_cc_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1\r\n',
                            ['alpha@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_depend(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_depend_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache_dependent_bug_changed(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha ~hppa\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        })
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_called()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_specified(self, bugz):
        """
        Test for depending on another bug when both bugs are listed
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_auto(self, bugz):
        """
        Test for depending on another bug with autofetching
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_failing(self, bugz):
        """
        Test that dependent sanity-check failure is not reported
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/mixed-keywords-4 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_no_fetch_deps(self, bugz):
        """
        Test for depending on another bug with --no-fetch-dependencies
        """

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_keywordreq_relaxed_syntax(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing alpha\r\n',
                            sanity_check=None,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_keywords_above(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n'
                            'test/amd64-testing-1 ^\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_keywords_partial_cc_match(self, bugz):
        """Test package list where some of the packages do not match CC"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560311: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64 hppa\r\n'
                            'test/amd64-testing-2 amd64\r\n',
                            cc=['hppa@gentoo.org'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cc_prefix(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 amd64 hppa amd64-linux '
                            'x86-macos sparc-freebsd\r\n',
                            keywords=['CC-ARCHES'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_allarches_add(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-5 amd64 hppa\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_allarches_extra_keywords(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-5 amd64 hppa alpha\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None)
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_allarches_remove(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            keywords=['ALLARCHES'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_allarches_leave_false(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-stable-hppa-testing-1 hppa\r\n',
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_allarches_leave_true(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            keywords=['ALLARCHES'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_expand_plist(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 *\r\n'
                            'test/amd64-testing-2 ^\r\n',
                            ['amd64@gentoo.org'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            new_package_list=['test/mixed-keywords-3 amd64 hppa\r\n'
                              'test/amd64-testing-2 amd64 hppa\r\n'])
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_expand_plist_cc_arches(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 *\r\n'
                            'test/amd64-testing-2 ^\r\n',
                            keywords=['CC-ARCHES'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            cc_add=['amd64@gentoo.org', 'hppa@gentoo.org', 'foo@example.com'],
            new_package_list=['test/mixed-keywords-3 \r\n'
                              'test/amd64-testing-2 \r\n'])
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_expand_plist_after_cc(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 *\r\n'
                            'test/amd64-testing-2 ^\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--cache-file', self.cache_file,
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None)
        self.post_verify()

        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 *\r\n'
                            'test/amd64-testing-2 ^\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            sanity_check=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--cache-file', self.cache_file,
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None,
            new_package_list=['test/mixed-keywords-3 \r\n'
                              'test/amd64-testing-2 \r\n'])
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_expand_plist_impossible(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3\r\n'
                            'test/amd64-testing-2 ^ hppa\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cc_arches_with_empty_keywords(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3\r\n',
                            keywords=['CC-ARCHES'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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
            cc_add=['amd64@gentoo.org', 'hppa@gentoo.org', 'foo@example.com'])
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cc_resolved_race(self, bugz):
        bugz_inst = self.bug_preset(bugz, keywords=['CC-ARCHES'],
                                    resolved=True)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            skip_tags=['nattka:skip'],
            unresolved=True)
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cc_unassigned(self, bugz):
        bugz_inst = self.bug_preset(bugz, keywords=['CC-ARCHES'],
                                    assigned_to='bug-wranglers@gentoo.org')
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, None)
        self.post_verify()

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_freshly_updated(self, bugz, add_keywords):
        """Test that freshly updated bugs are skipped"""
        bugz_inst = self.bug_preset(bugz,
                                    last_change_time=datetime.datetime(
                                        2020, 1, 1, 12, 0, 0))

        with patch('nattka.__main__.datetime.datetime',
                   new=FakeDateTime(datetime.datetime(2020, 1, 1, 12, 0, 30))):
            self.assertEqual(
                main(self.common_args + ['sanity-check', '--update-bugs',
                                         '560322']),
                0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.__main__.NattkaBugzilla')
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

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%B',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/alpha-amd64-hppa-testing: Stabilize 2 amd64 hppa, #560322

Signed-off-by: test <test@example.com>


test/alpha-amd64-hppa-testing/alpha-amd64-hppa-testing-2.ebuild
test
test@example.com
test/amd64-testing: Stabilize 1 amd64, #560322

Signed-off-by: test <test@example.com>


test/amd64-testing/amd64-testing-1.ebuild
''')

    @unittest.skipIf(not have_nattka_depgraph,
                     'networkx required for dep sorting')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_commit_dep_sorting(self, bugz):
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=self.repo.location).wait() == 0

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%B',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/amd64-testing-deps: Stabilize 1 amd64, #560322

Signed-off-by: test <test@example.com>


test/amd64-testing-deps/amd64-testing-deps-1.ebuild
test
test@example.com
test/amd64-testing: Stabilize 1 amd64, #560322

Signed-off-by: test <test@example.com>


test/amd64-testing/amd64-testing-1.ebuild
''')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_commit_allarches(self, bugz):
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=self.repo.location).wait() == 0

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 amd64 hppa\r\n'
                            'test/mixed-keywords-4 amd64 hppa\r\n',
                            sanity_check=True,
                            keywords=['ALLARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322']),
            0)
        self.assertEqual(
            main(self.common_args + ['commit', '-a', 'amd64', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%B',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/mixed-keywords: Stabilize 4 ALLARCHES, #560322

Signed-off-by: test <test@example.com>


test/mixed-keywords/mixed-keywords-4.ebuild
test
test@example.com
test/mixed-keywords: Stabilize 3 ALLARCHES, #560322

Signed-off-by: test <test@example.com>


test/mixed-keywords/mixed-keywords-3.ebuild
''')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_commit_allarches_ignore(self, bugz):
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.name', 'test'],
            cwd=self.repo.location).wait() == 0
        assert subprocess.Popen(
            ['git', 'config', '--local', 'user.email', 'test@example.com'],
            cwd=self.repo.location).wait() == 0

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/mixed-keywords-3 amd64 hppa\r\n'
                            'test/mixed-keywords-4 amd64 hppa\r\n',
                            sanity_check=True,
                            keywords=['ALLARCHES']),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['apply', '-a', 'amd64', '560322',
                                     '--ignore-allarches']),
            0)
        self.assertEqual(
            main(self.common_args + ['commit', '-a', 'amd64', '560322',
                                     '--ignore-allarches']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])

        s = subprocess.Popen(['git', 'log', '--format=%an\n%ae\n%B',
                              '--name-only'],
                             cwd=self.repo.location,
                             stdout=subprocess.PIPE)
        sout, _ = s.communicate()
        self.assertEqual(sout.decode(),
                         '''test
test@example.com
test/mixed-keywords: Stabilize 4 amd64, #560322

Signed-off-by: test <test@example.com>


test/mixed-keywords/mixed-keywords-4.ebuild
test
test@example.com
test/mixed-keywords: Stabilize 3 amd64, #560322

Signed-off-by: test <test@example.com>


test/mixed-keywords/mixed-keywords-3.ebuild
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
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=initial_status,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_n(self, bugz):
        """Test processing with -n"""
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_not_called()
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_cache(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322', '--cache-file',
                                     self.cache_file]),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called()

        with patch('nattka.__main__.add_keywords') as add_keywords:
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_malformed_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            '<>amd64-testing-deps-1 ~alpha\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_malformed_plist_cache_empty_reported(
            self, bugz, add_keywords):
        """
        Regression test for reporting an exception-failure when cache
        is used and previous comment matches
        """
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            '<>amd64-testing-deps-1 ~alpha\r\n',
                            sanity_check=False,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_disallowed_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            '>=test/amd64-testing-deps-1 ~alpha\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_non_matched_plist(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.add_keywords')
    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_non_matched_keywords(self, bugz, add_keywords):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 amd64 ~mysuperarch\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_masked_package(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/masked-package-1 amd64\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> package '
            'masked: test/masked-package-1')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_masked_in_all_profiles(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/profile-masked-package-1 amd64\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Unable to check for sanity:\n\n> package '
            'masked: test/profile-masked-package-1, in all profiles '
            'for arch: amd64')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_reason_masked_in_one_profile(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/partially-masked-package-1 amd64\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = (
            bugz_inst.find_bugs.return_value)
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, 'Sanity check failed:\n\n'
                           '> test/partially-masked-package-1\n'
                           '>   bdepend ~amd64 stable profile '
                           'amd64-second (1 total)\n'
                           '>     test/alpha-testing-deps')

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_invalid(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_and_bug_invalid(self, bugz):
        """Verify that issues with current bug take precedence over deps"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/enoent-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_depend_missing_keywords(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            depends=[560311],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.resolve_dependencies.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1',
                            blocks=[560322],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_security(self, bugz):
        bugz_inst = bugz.return_value
        bugs = {
            # non-security bugs
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 alpha ~hppa\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            560324: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            # security bugs
            560332: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 alpha ~hppa\r\n',
                            keywords=['SECURITY'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            560334: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            keywords=['SECURITY'],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            560336: BugInfo(BugCategory.STABLEREQ,
                            'test/alpha-amd64-hppa-testing-2 amd64 hppa\r\n',
                            security=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.find_bugs.return_value = bugs
        bugz_inst.resolve_dependencies.return_value = bugs

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs',
                                     '--security']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            skip_tags=['nattka:skip'],
            unresolved=True)
        bugz_inst.update_status.assert_any_call(560332, True, None)
        bugz_inst.update_status.assert_any_call(560334, True, None)
        bugz_inst.update_status.assert_any_call(560336, True, None)
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_security_add_kw(self, bugz):
        bugz_inst = bugz.return_value
        bugs = {
            # a security bug without package list
            560324: BugInfo(BugCategory.STABLEREQ,
                            '',
                            security=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            # respective stablereq
            560334: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n',
                            blocks=[560324],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.find_bugs.return_value = bugs
        bugz_inst.resolve_dependencies.return_value = bugs

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            skip_tags=['nattka:skip'],
            unresolved=True)
        bugz_inst.update_status.assert_called_with(
            560334, True, None, keywords_add=['SECURITY'])
        self.post_verify()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_sanity_security_add_kw_kwreq(self, bugz):
        bugz_inst = bugz.return_value
        bugs = {
            # a security bug without package list
            560324: BugInfo(BugCategory.STABLEREQ,
                            '',
                            security=True,
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
            # respective stablereq
            560334: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 alpha ~hppa\r\n',
                            blocks=[560324],
                            last_change_time=datetime.datetime(
                                2020, 1, 1, 12, 0, 0)),
        }
        bugz_inst.find_bugs.return_value = bugs
        bugz_inst.resolve_dependencies.return_value = bugs

        self.assertEqual(
            main(self.common_args + ['sanity-check', '--update-bugs']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            category=[BugCategory.KEYWORDREQ, BugCategory.STABLEREQ],
            skip_tags=['nattka:skip'],
            unresolved=True)
        bugz_inst.update_status.assert_called_with(
            560334, True, None, keywords_add=['SECURITY'])
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
            bugs[100000 + i] = BugInfo(BugCategory.STABLEREQ,
                                       'test/amd64-testing-1 amd64\r\n',
                                       last_change_time=datetime.datetime(
                                           2020, 1, 1, 12, 0, 0))

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = bugs
        bugz_inst.resolve_dependencies.return_value = bugs
        return bugz_inst

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_keywordreq(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--keywordreq']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.KEYWORDREQ])

    @patch('nattka.__main__.NattkaBugzilla')
    def test_stablereq(self, bugz):
        bugz_inst = bugz.return_value
        self.assertEqual(
            main(self.common_args + ['sanity-check', '--stablereq']),
            0)
        bugz_inst.find_bugs.assert_called_with(
            skip_tags=['nattka:skip'],
            unresolved=True,
            category=[BugCategory.STABLEREQ])

    @patch('nattka.__main__.NattkaBugzilla')
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


class ResolveTests(IntegrationTestCase):
    """Tests for resolve command"""

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_one_of_many(self, bugz):
        """Test resolve with one of many arches done"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', 'hppa', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322, ['hppa@gentoo.org'], 'hppa done', False)

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_all_of_many(self, bugz):
        """Test resolve with all of many arches done"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_security(self, bugz):
        """Test that security bugs are not closed"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_closed(self, bugz):
        """Test that closed bugs do not get their resolution changed"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_no_resolve(self, bugz):
        """Test that --no-resolve inhibits resolving bugs"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
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

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_pretend(self, bugz):
        """Test that --pretend inhibits updates"""
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', '*', '560322',
                                     '--pretend']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_not_called()

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_allarches(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            keywords=['ALLARCHES']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', 'hppa', '560322']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322, ['amd64@gentoo.org', 'hppa@gentoo.org'],
            'amd64 hppa (ALLARCHES) done\n\nall arches done', True)

    @patch('nattka.__main__.NattkaBugzilla')
    def test_resolve_allarches_ignore(self, bugz):
        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/example-1\r\n',
                            ['amd64@gentoo.org', 'hppa@gentoo.org'],
                            keywords=['ALLARCHES']),
        }
        self.assertEqual(
            main(self.common_args + ['resolve', '-a', 'hppa', '560322',
                                     '--ignore-allarches']),
            0)
        bugz_inst.find_bugs.assert_called_with(bugs=[560322])
        bugz_inst.resolve_bug.assert_called_with(
            560322, ['hppa@gentoo.org'], 'hppa done', False)


class MakePackageListTests(IntegrationTestCase):
    """Tests for make-package-list command"""

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_one_iteration(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/a']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/a *\n\n')

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_two_iterations(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/b']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/b *\n'
            'make-pkg-list/a ^\n')

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_three_iterations(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/c']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/c *\n'
            'make-pkg-list/b ^\n'
            'make-pkg-list/a ^\n')

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_three_iterations_common_package(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/c-common']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/c-common *\n'
            'make-pkg-list/a ^\n'
            'make-pkg-list/b ^\n')

    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_red_herring(self, sout):
        """Test a red herring due to || deps"""
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/red-herring']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/red-herring *\n'
            'make-pkg-list/a ^\n')

    @unittest.expectedFailure
    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_less_than_dep(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/less-than']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/less-than *\n'
            '<make-pkg-list/less-than-dep-2 ^\n')

    @unittest.expectedFailure
    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_usedep(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/usedep']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/usedep *\n'
            '<make-pkg-list/less-than-dep-2 ^\n')

    @unittest.expectedFailure
    @patch('nattka.__main__.sys.stdout', new_callable=io.StringIO)
    def test_profile_masked_usedep(self, sout):
        self.assertEqual(
            main(self.common_args + ['make-package-list',
                                     'make-pkg-list/profile-masked-usedep']),
            0)
        self.assertEqual(
            sout.getvalue(),
            'make-pkg-list/profile-masked-usedep *\n'
            'make-pkg-list/a ^\n')
