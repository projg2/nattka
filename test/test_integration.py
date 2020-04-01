# (c) 2020 Michał Górny
# 2-clause BSD license

""" Integration tests. """

import abc
import datetime
import json
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
from nattka.cli import main

from test import get_test_repo


class IntegrationTestCase(object):
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
        basedir = Path(__file__).parent
        for subdir in ('conf', 'data'):
            shutil.copytree(basedir / subdir,
                            tempdir_path / subdir,
                            symlinks=True)

        self.repo = get_test_repo(tempdir_path)

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

    def make_cache(self,
                   bugz_inst: MagicMock,
                   last_check: datetime.datetime = datetime.datetime.utcnow(),
                   package_list: typing.Optional[str] = None,
                   sanity_check: typing.Optional[bool] = None
                   ) -> str:
        """
        Write a cache file and return the path to it.
        """
        fn = Path(self.tempdir.name) / 'cache.json'
        with open(fn, 'w') as f:
            json.dump({
                'bugs': {
                    '560322': {
                        'last-check': last_check.isoformat(),
                        'package-list':
                            package_list if package_list is not None
                            else bugz_inst.fetch_package_list
                            .return_value[560322].atoms,
                        'check-res': sanity_check,
                    },
                },
            }, f)
        return str(fn)


class IntegrationNoActionTestCase(IntegrationTestCase,
                                  metaclass=abc.ABCMeta):
    """
    Test case for a bug that can not be processed.
    """

    @abc.abstractmethod
    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        """ Preset bugzilla mock. """
        pass

    @abc.abstractproperty
    def reset_msg(self):
        """ Expected reset message. """
        pass

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_skip_apply(self, bugz, add_keywords):
        """
        Test skipping a bug that is not suitable for processing
        in 'apply' command.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_skip(self, bugz, add_keywords):
        """
        Test skipping a bug that is not suitable for processing.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_reset_n(self, bugz, add_keywords):
        """
        Test skipping a bug that needs sanity-check reset, with '-n'.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '-n', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_reset(self, bugz, add_keywords):
        """
        Test resetting sanity-check for a bug.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_called_with(
            560322, None, self.reset_msg)


class IntegrationEmptyPackagesTests(IntegrationNoActionTestCase,
                                    unittest.TestCase):
    """
    Test for a bug where package list is empty.
    """

    reset_msg = 'Resetting sanity check; package list is empty.'

    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            '   \r\n'
                            '\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationEmptyKeywordsTests(IntegrationNoActionTestCase,
                                    unittest.TestCase):
    """
    Test for a bug where keywords can not be determined (neither fully
    specified nor in CC).
    """

    reset_msg = ('Resetting sanity check; keywords are not fully '
                 'specified and arches are not CC-ed.')

    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n'
                            'test/alpha-amd64-hppa-testing-2\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationWrongCategoryTests(IntegrationTestCase,
                                    unittest.TestCase):
    """
    Test for a bug in non-keywordreq/stablereq category.
    """

    def bug_preset(self,
                   bugz: MagicMock
                   ) -> MagicMock:
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(None,
                            '',
                            [], [], [], None),
        }
        return bugz_inst

    @patch('nattka.cli.match_package_list')
    @patch('nattka.cli.NattkaBugzilla')
    def test_wrong_category_apply(self, bugz, match_package_list):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        match_package_list.assert_not_called()

    @patch('nattka.cli.match_package_list')
    @patch('nattka.cli.NattkaBugzilla')
    def test_wrong_category_process(self, bugz, match_package_list):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        match_package_list.assert_not_called()
        bugz_inst.update_status.assert_not_called()


class IntegrationSuccessTestCase(IntegrationTestCase,
                                 metaclass=abc.ABCMeta):
    """
    Integration test case that passes sanity-check.
    """

    @abc.abstractmethod
    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        """ Preset bugzilla mock. """
        pass

    def post_verify(self):
        """ Verify that the original data has been restored. """
        assert isinstance(self, unittest.TestCase)
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('~amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', '~amd64', '~hppa'))

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_success_n(self, bugz):
        """ Test processing with -n. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '-n', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_success(self, bugz):
        """ Test setting new success. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(560322, True, None)

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_success_from_success(self, bugz):
        """
        Test non-update when bug was marked sanity-check+ already.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_success_from_failure(self, bugz):
        """ Test transition from failure to success. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(
            560322, True, 'All sanity-check issues have been resolved')


class IntegrationSuccessTests(IntegrationSuccessTestCase, unittest.TestCase):
    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        """ Preset bugzilla mock. """
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.STABLEREQ,
                            'test/amd64-testing-1 amd64\r\n'
                            'test/alpha-amd64-hppa-testing-2 amd64 hppa\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst

    @patch('nattka.cli.NattkaBugzilla')
    def test_apply(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['apply', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])

        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', 'amd64', 'hppa'))

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cached(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check+ is respected.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        cache = self.make_cache(bugz_inst, sanity_check=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_expired(self, bugz, add_keywords):
        """
        Test that expired cached entry for sanity-check+ is ignored.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        last_check = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        cache = self.make_cache(bugz_inst,
                                last_check=last_check,
                                sanity_check=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_plist_changed(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check+ is ignored if package
        list changes.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        cache = self.make_cache(bugz_inst,
                                package_list='test/foo',
                                sanity_check=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_result_changed(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check+ is ignored
        if sanity-check flag changed.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        cache = self.make_cache(bugz_inst,
                                sanity_check=False)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()


class IntegrationDependSuccessTests(IntegrationSuccessTestCase,
                                    unittest.TestCase):
    """
    Tests for sanity-check result depending on dependant bug.
    """

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        # TODO: we hackily add dependent bug to the return value now
        # this will probably make more sense when fetch_package_list()
        # has recursive fetching support
        bugz_inst.fetch_package_list.return_value = {
            560311: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 ~alpha\r\n',
                            [], [], [560322], True),
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            [], [560311], [], initial_status),
        }
        return bugz_inst


class IntegrationFailureTestCase(IntegrationTestCase,
                                 metaclass=abc.ABCMeta):
    """
    Integration test case that fails sanity-check.
    """

    @abc.abstractproperty
    def fail_msg(self) -> str:
        """ Expected failure message. """
        pass

    @abc.abstractmethod
    def bug_preset(self,
                   bugz: MagicMock,
                   initial_status: typing.Optional[bool] = None
                   ) -> MagicMock:
        """ Preset bugzilla mock. """
        pass

    def post_verify(self) -> None:
        """ Verify that the original data has been restored. """
        assert isinstance(self, unittest.TestCase)
        self.assertEqual(
            self.get_package('=test/amd64-testing-deps-1').keywords,
            ('~amd64',))

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure_n(self, bugz):
        """ Test processing with -n. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '-n', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure(self, bugz):
        """ Test setting new failure. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure_no_comment(self, bugz):
        """
        Test setting failure when bug is sanity-check- without a comment.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz)
        bugz_inst.get_latest_comment.return_value = None
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure_from_other_failure(self, bugz):
        """
        Test setting failure when bug is sanity-check- with a different
        failure.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = (
            'Sanity check failed:\n\n> nonsolvable depset(rdepend) '
            'keyword(~alpha) stable profile (alpha) (1 total): '
            'solutions: [ test/frobnicate ]')
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure_from_same_failure(self, bugz):
        """
        Test non-update when bug was marked sanity-check- already.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = self.fail_msg
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.NattkaBugzilla')
    def test_process_failure_from_success(self, bugz):
        """ Test transition from success to failure. """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322']),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        bugz_inst.update_status.assert_called_with(
            560322, False, self.fail_msg)


class IntegrationFailureTests(IntegrationFailureTestCase,
                              unittest.TestCase):
    fail_msg = ('Sanity check failed:\n\n> nonsolvable depset(rdepend) '
                'keyword(~alpha) stable profile (alpha) (1 total): '
                'solutions: [ test/amd64-testing ]')

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-deps-1 ~alpha\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cached(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check- is respected.
        """
        assert isinstance(self, unittest.TestCase)
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        cache = self.make_cache(bugz_inst, sanity_check=False)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_not_called()
        bugz_inst.update_status.assert_not_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_expired(self, bugz, add_keywords):
        """
        Test that expired cached entry for sanity-check- is ignored.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = self.fail_msg
        last_check = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        cache = self.make_cache(bugz_inst,
                                last_check=last_check,
                                sanity_check=False)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_plist_changed(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check- is ignored if package
        list changes.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = self.fail_msg
        cache = self.make_cache(bugz_inst,
                                package_list='test/foo',
                                sanity_check=False)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()

    @patch('nattka.cli.add_keywords')
    @patch('nattka.cli.NattkaBugzilla')
    def test_process_cache_result_changed(self, bugz, add_keywords):
        """
        Test that cached entry for sanity-check- is ignored
        if sanity-check flag changed.
        """
        bugz_inst = self.bug_preset(bugz, initial_status=False)
        bugz_inst.get_latest_comment.return_value = self.fail_msg
        cache = self.make_cache(bugz_inst,
                                sanity_check=True)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '560322',
                                     '--cache-file', cache]),
            0)
        bugz_inst.fetch_package_list.assert_called_with([560322])
        add_keywords.assert_called()


class IntegrationMalformedPackageListTests(IntegrationFailureTestCase,
                                           unittest.TestCase):
    fail_msg = ('Unable to check for sanity:\n\n> invalid package spec: '
                '<>amd64-testing-deps-1')

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            '<>amd64-testing-deps-1 ~alpha\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationNonequalsPackageListTests(IntegrationFailureTestCase,
                                           unittest.TestCase):
    fail_msg = ('Unable to check for sanity:\n\n> disallowed package '
                'spec (only = allowed): >=test/amd64-testing-deps-1')

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            '>=test/amd64-testing-deps-1 ~alpha\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationNonMatchedPackageListTests(IntegrationFailureTestCase,
                                            unittest.TestCase):
    fail_msg = ("Unable to check for sanity:\n\n> no match for package: "
                "test/enoent-7")

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/enoent-7 ~alpha\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationNonMatchedKeywordListTests(IntegrationFailureTestCase,
                                            unittest.TestCase):
    fail_msg = ("Unable to check for sanity:\n\n> incorrect keywords: "
                "mysuperarch")

    def bug_preset(self, bugz, initial_status=None):
        bugz_inst = bugz.return_value
        bugz_inst.fetch_package_list.return_value = {
            560322: BugInfo(BugCategory.KEYWORDREQ,
                            'test/amd64-testing-1 amd64 ~mysuperarch\r\n',
                            [], [], [], initial_status),
        }
        return bugz_inst


class IntegrationLimiterTests(IntegrationTestCase, unittest.TestCase):
    """
    Tests for limiting the number of processed bugs.
    """

    def bug_preset(self,
                   bugz: MagicMock
                   ) -> MagicMock:
        bugs = {}
        for i in range(10):
            bugs[100000 + i] = BugInfo(BugCategory.KEYWORDREQ,
                                       'test/amd64-testing-1 ~amd64\r\n',
                                       [], [], [], None)

        bugz_inst = bugz.return_value
        bugz_inst.find_bugs.return_value = bugs
        return bugz_inst

    @patch('nattka.cli.NattkaBugzilla')
    def test_bug_limit(self, bugz):
        bugz_inst = self.bug_preset(bugz)
        self.assertEqual(
            main(self.common_args + ['process-bugs', '--bug-limit', '5']),
            0)
        bugz_inst.find_bugs.assert_called_with(None)
        self.assertEqual(bugz_inst.update_status.call_count, 5)
        bugz_inst.update_status.assert_has_calls(
            [unittest.mock.call(100009, True, None),
             unittest.mock.call(100008, True, None),
             unittest.mock.call(100007, True, None),
             unittest.mock.call(100006, True, None),
             unittest.mock.call(100005, True, None)])
