# (c) 2020-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

""" Tests for Bugzilla interaction. """

import datetime
import json
import typing
import unittest

from pathlib import Path
from urllib.parse import urlsplit

import yaml

from pkgcore.bugzilla.testing import Cassette, response
from pkgcore.bugzilla import (Bug, BugCategory, BugQuery, Bugzilla,
                              BugUpdate, FlagStatus, ListChange,
                              NewComment, PackageList, Resolution,
                              RuntimeTesting, Status)

from nattka.bugzilla import make_bugzilla, split_dependent_bugs
from test.bug import mk_bug


API_ENDPOINT = 'http://127.0.0.1:33113/rest'
API_KEY = 'xH3pICxBPtyhTrFjvuuzIaNYek9uqisCJzR9izAZ'
USER_API_KEY = 'dhaGUYKZOGGVRmg4k24wEXaWRHntUjIlW6eqePu1'
BUGZILLA_USERNAME = 'nattka' + '@gentoo.org'
USER_BUGZILLA_USERNAME = 'test@example.com'

CASSETTES = Path(__file__).parent / 'bugzilla'


def replay(name: str) -> Cassette:
    """Serve a cassette recorded against the dockerised Bugzilla.

    Responses are queued per endpoint rather than in one global order, so the
    exact request order need not match what was recorded; only the sequence of
    answers from any single endpoint does.  The recordings predate the move to
    pkgcore.bugzilla, which issues the same requests in a slightly different
    order.
    """
    data = yaml.safe_load((CASSETTES / name).read_text())
    queues: typing.Dict[tuple, list] = {}
    for interaction in data['interactions']:
        request = interaction['request']
        key = (request['method'], urlsplit(request['uri']).path)
        queues.setdefault(key, []).append(
            interaction['response']['body']['string'])

    def route(call):
        key = (call.method, call.path)
        bodies = queues.get(key)
        assert bodies, f'no recorded response for {key[0]} {key[1]}'
        # the last answer stands in for any repeat of the same request
        return json.loads(bodies.pop(0) if len(bodies) > 1 else bodies[0])

    return Cassette(base_url='http://127.0.0.1:33113').always(response(route))


# what nattka reads off a bug; the rest of Bug is Bugzilla bookkeeping the
# expected-data fixture has no opinion about
COMPARED = ('category', 'cc', 'depends_on', 'blocks', 'sanity_check',
            'security', 'resolved', 'keywords', 'whiteboard', 'assigned_to',
            'last_change_time', 'runtime_testing_required')


def projected(bugs: typing.Dict[int, Bug]) -> typing.Dict[int, tuple]:
    """Reduce bugs to the fields under test.

    The package list is compared without its trailing newline, which Bugzilla
    does not send and only the fixtures carry.
    """
    return {no: (str(bug.package_list).rstrip('\r\n'),
                 tuple(getattr(bug, f) for f in COMPARED))
            for no, bug in bugs.items()}


class ReplayTestCase(unittest.TestCase):
    """Installs the cassette named after the running test"""

    bz: Bugzilla
    api_key = API_KEY
    maxDiff = None

    def latest_comment(self,
                       bugno: int,
                       username: typing.Optional[str] = None
                       ) -> typing.Optional[str]:
        """Text of the newest comment by `username`, or None"""
        comment = self.bz.latest_comment(bugno, creator=username)
        return comment.text if comment is not None else None

    def set_status(self, bugno: int, status: typing.Optional[bool],
                   **kwargs: typing.Any) -> None:
        """Set the sanity-check flag the way nattka does"""
        self.bz.mark_own_comments_obsolete(bugno)
        self.bz.update(bugno, BugUpdate.sanity_check(status, **kwargs))

    def setUp(self):
        cassette = replay(self.id().rsplit('.', 1)[-1])
        installed = cassette.installed()
        installed.__enter__()
        self.addCleanup(installed.__exit__, None, None, None)
        self.cassette = cassette
        self.bz = make_bugzilla(self.api_key, API_ENDPOINT)


class BugzillaTests(ReplayTestCase):

    def get_bugs(self,
                 req: typing.Iterable[int]
                 ) -> typing.Dict[int, Bug]:
        """Return expected data for specified bugs"""
        bugs = {1: mk_bug(None, '\r\n', blocks=[2],
                          assigned_to='test@example.com',
                          last_change_time=datetime.datetime(
            2020, 4, 3, 13, 22, 41,
            tzinfo=datetime.timezone.utc)),
            2: mk_bug(BugCategory.KEYWORDREQ,
                      'dev-python/unittest-mixins-1.6\r\n'
                      'dev-python/coverage-4.5.4\r\n',
                      [f'{x}@gentoo.org' for x in ('alpha',
                                                   'hppa')],
                      depends=[1],
                      blocks=[9],
                      sanity_check=True,
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 3, 13, 34, 59,
                          tzinfo=datetime.timezone.utc)),
            3: mk_bug(BugCategory.STABLEREQ,
                      'dev-python/mako-1.1.0 amd64\r\n',
                      [f'{x}@gentoo.org' for x in ('amd64',)],
                      depends=[7],
                      keywords=['STABLEREQ'],
                      sanity_check=False,
                      assigned_to='bug-wranglers@gentoo.org',
                      last_change_time=datetime.datetime(
                          2020, 11, 26, 9, 42, 55,
                          tzinfo=datetime.timezone.utc),
                      runtime_testing_required=(
                          RuntimeTesting.MANUAL)),
            4: mk_bug(BugCategory.KEYWORDREQ,
                      'dev-python/urllib3-1.25.8\r\n'
                      'dev-python/trustme-0.6.0\r\n'
                      'dev-python/brotlipy-0.7.0\r\n',
                      [f'{x}@gentoo.org' for x in ('hppa',)],
                      keywords=['KEYWORDREQ'],
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 3, 13, 34, 55,
                          tzinfo=datetime.timezone.utc),
                      runtime_testing_required=(
                          RuntimeTesting.YES)),
            5: mk_bug(None,
                      'app-arch/arj-3.10.22-r7 amd64 hppa\r\n',
                      ['test@example.com'],
                      whiteboard='test whiteboard',
                      security=True,
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 10, 9, 47, 22,
                          tzinfo=datetime.timezone.utc),
                      runtime_testing_required=(
                          RuntimeTesting.YES)),
            6: mk_bug(None,
                      'sys-kernel/gentoo-sources-4.1.6\r\n',
                      security=True,
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 3, 13, 31, 19,
                          tzinfo=datetime.timezone.utc),
                      runtime_testing_required=(
                          RuntimeTesting.YES)),
            7: mk_bug(BugCategory.STABLEREQ,
                      'dev-python/pytest-5.4.1\r\n',
                      blocks=[3],
                      keywords=['ALLARCHES'],
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 3, 13, 28, 17,
                          tzinfo=datetime.timezone.utc),
                      runtime_testing_required=(
                          RuntimeTesting.YES)),
            8: mk_bug(BugCategory.STABLEREQ,
                      'dev-lang/python-3.7.7\r\n',
                      resolved=True,
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 4, 7, 7, 56,
                          tzinfo=datetime.timezone.utc)),
            9: mk_bug(BugCategory.KEYWORDREQ,
                      'dev-python/frobnicate-11\r\n',
                      depends=[2],
                      assigned_to='test@example.com',
                      last_change_time=datetime.datetime(
                          2020, 4, 5, 14, 35, 59,
                          tzinfo=datetime.timezone.utc)),
        }
        for k in list(bugs):
            if k not in req:
                del bugs[k]
        return bugs

    def test_whoami(self):
        """ Test whoami(). """
        self.assertEqual(self.bz.whoami().name, BUGZILLA_USERNAME)

    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            projected(self.bz.search(BugQuery.ids([1, 2, 3, 4, 8]))),
            projected(self.get_bugs([1, 2, 3, 4, 8])))

    def test_fetch_bugs_keywordreq(self):
        """Test getting and filtering to keywordreqs."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([1, 2, 3, 4, 8])
                & BugQuery.category(BugCategory.KEYWORDREQ))),
            projected(self.get_bugs([2, 4])))

    def test_fetch_bugs_stablereq(self):
        """Test getting and filtering to stablereqs."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([1, 2, 3, 4, 8])
                & BugQuery.category(BugCategory.STABLEREQ))),
            projected(self.get_bugs([3, 8])))

    def test_fetch_bugs_any(self):
        """Test getting and filtering to keywordreqs and stablereqs."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([1, 2, 3, 4, 8])
                & BugQuery.category(BugCategory.KEYWORDREQ,
                                    BugCategory.STABLEREQ))),
            projected(self.get_bugs([2, 3, 4, 8])))

    def test_fetch_sanity_check_passed(self):
        """Test filtering bugs by sanity-check+."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([2, 3, 4, 6])
                & BugQuery.flag('sanity-check', FlagStatus.GRANTED))),
            projected(self.get_bugs([2])))

    def test_fetch_sanity_check_failed(self):
        """Test filtering bugs by sanity-check-."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([2, 3, 4, 6])
                & BugQuery.flag('sanity-check', FlagStatus.DENIED))),
            projected(self.get_bugs([3])))

    def test_fetch_sanity_check_both(self):
        """Test filtering bugs by sanity-check+/-."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.ids([2, 3, 4, 6])
                & BugQuery.flag('sanity-check',
                                FlagStatus.GRANTED,
                                FlagStatus.DENIED))),
            projected(self.get_bugs([2, 3])))

    def test_fetch_bugs_cc(self):
        """Test filtering bugs by CC."""
        self.assertEqual(
            projected(self.bz.search(BugQuery.ids([1, 3, 4, 8])
                                     & BugQuery.cc('hppa@gentoo.org'))),
            projected(self.get_bugs([4])))

    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(
            projected(
                self.bz.search(
                    BugQuery.category(BugCategory.KEYWORDREQ))),
            projected(self.get_bugs([2, 4, 9])))

    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(
            projected(
                self.bz.search(
                    BugQuery.category(BugCategory.STABLEREQ))),
            projected(self.get_bugs([3, 7, 8])))

    def test_find_bugs_cc(self):
        """Test finding bugs by CC."""
        self.assertEqual(
            projected(self.bz.search(BugQuery.cc('hppa@gentoo.org'))),
            projected(self.get_bugs([2, 4])))

    def test_find_sanity_check_passed(self):
        """Test finding bugs that are flagged sanity-check+."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.flag('sanity-check', FlagStatus.GRANTED))),
            projected(self.get_bugs([2])))

    def test_find_sanity_check_failed(self):
        """Test finding bugs that are flagged sanity-check-."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.flag('sanity-check', FlagStatus.DENIED))),
            projected(self.get_bugs([3])))

    def test_find_sanity_check_both(self):
        """Test finding bugs that are flagged sanity-check+ or -."""
        self.assertEqual(
            projected(self.bz.search(
                BugQuery.flag('sanity-check',
                              FlagStatus.GRANTED,
                              FlagStatus.DENIED))),
            projected(self.get_bugs([2, 3])))

    def test_find_bugs_personal_tags(self):
        """Test finding bugs by personal tags."""
        self.assertEqual(
            projected(self.bz.search(BugQuery.without_tags('nattka:skip'))),
            projected(self.get_bugs([1, 2, 4, 5, 6, 7, 8, 9])))

    def test_find_bugs_unresolved(self):
        """Test finding unresolved bugs"""
        self.assertEqual(
            projected(self.bz.search(BugQuery.unresolved())),
            projected(self.get_bugs([1, 2, 3, 4, 5, 6, 7, 9])))

    def test_resolve_dependencies(self):
        """Test resolving missing dependencies recursively"""
        bz = self.bz.search(BugQuery.ids([9]))
        self.assertEqual(
            projected(self.bz.resolve_dependencies(bz)),
            projected(self.get_bugs([1, 2, 9])))

    def test_get_latest_comment(self):
        """ Test getting latest self-comment. """
        self.assertEqual(
            self.latest_comment(3, BUGZILLA_USERNAME),
            'sanity check failed!')

    def test_get_latest_comment_whoami(self):
        """ Test getting latest self-comment with whoami(). """
        self.assertEqual(
            self.latest_comment(3),
            'sanity check failed!')


class DestructiveBugzillaTests(ReplayTestCase):

    def test_set_status(self):
        """Test setting sanity-check status"""
        self.assertIsNone(
            self.bz.search(BugQuery.ids([5]))[5].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(5, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(5, True)

        self.assertTrue(
            self.bz.search(BugQuery.ids([5]))[5].sanity_check)
        self.assertIsNone(
            self.latest_comment(5, BUGZILLA_USERNAME))

    def test_set_status_and_mark_obsolete(self):
        """Test setting sanity-check status and marking comments obsolete"""
        self.assertFalse(
            self.bz.search(BugQuery.ids([3]))[3].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNotNone(
            self.latest_comment(3, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(3, False)

        self.assertFalse(
            self.bz.search(BugQuery.ids([3]))[3].sanity_check)
        self.assertIsNotNone(
            self.latest_comment(3, BUGZILLA_USERNAME))

    def test_set_status_and_comment(self):
        """Test setting sanity-check status and commenting"""
        self.assertIsNone(
            self.bz.search(BugQuery.ids([6]))[6].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(6, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(6, False, comment='sanity check failed!\r\n')

        self.assertFalse(
            self.bz.search(BugQuery.ids([6]))[6].sanity_check)
        self.assertEqual(
            self.latest_comment(6, BUGZILLA_USERNAME),
            'sanity check failed!')

    def test_reset_status(self):
        """Test resetting sanity-check status"""
        self.assertTrue(
            self.bz.search(BugQuery.ids([2]))[2].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(2, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(2, None)

        self.assertIsNone(
            self.bz.search(BugQuery.ids([2]))[2].sanity_check)
        self.assertIsNone(
            self.latest_comment(2, BUGZILLA_USERNAME))

    def test_set_status_and_cc(self):
        bug = self.bz.search(BugQuery.ids([6]))[6]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.cc,
            (),
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(6, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(6, True,
                        cc=ListChange.adding('amd64@gentoo.org',
                                             'hppa@gentoo.org'))

        bug = self.bz.search(BugQuery.ids([6]))[6]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.cc, ('amd64@gentoo.org', 'hppa@gentoo.org'))
        self.assertIsNone(
            self.latest_comment(6, BUGZILLA_USERNAME))

    def test_set_status_and_add_keywords(self):
        bug = self.bz.search(BugQuery.ids([8]))[8]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.keywords,
            (),
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(8, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(8, True, keywords=ListChange.adding('ALLARCHES'))

        bug = self.bz.search(BugQuery.ids([8]))[8]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.keywords, ('ALLARCHES',))
        self.assertIsNone(
            self.latest_comment(8, BUGZILLA_USERNAME))

    def test_set_status_and_remove_keywords(self):
        bug = self.bz.search(BugQuery.ids([7]))[7]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.keywords,
            ('ALLARCHES',),
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(7, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(7, True, keywords=ListChange.removing('ALLARCHES'))

        bug = self.bz.search(BugQuery.ids([7]))[7]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.keywords, ())
        self.assertIsNone(
            self.latest_comment(7, BUGZILLA_USERNAME))

    def test_set_status_and_package_list(self):
        bug = self.bz.search(BugQuery.ids([9]))[9]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            str(bug.package_list),
            'dev-python/frobnicate-11',
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.latest_comment(9, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.set_status(
            9, True,
            package_list=PackageList(
                'dev-python/frobnicate-11 amd64 x86\r\n'))

        bug = self.bz.search(BugQuery.ids([9]))[9]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(
            str(bug.package_list), 'dev-python/frobnicate-11 amd64 x86')
        self.assertIsNone(
            self.latest_comment(9, BUGZILLA_USERNAME))


class DestructiveUserBugzillaTests(ReplayTestCase):
    api_key = USER_API_KEY

    def test_uncc_arch(self):
        """Test unCC-ing an arch from a bug without closing it"""
        bug = self.bz.search(BugQuery.ids([2]))[2]
        self.assertEqual(
            bug.cc,
            ('alpha@gentoo.org', 'hppa@gentoo.org'),
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.latest_comment(2, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.update(2, BugUpdate(
            status=Status.IN_PROGRESS,
            cc=ListChange.removing('hppa@gentoo.org'),
            comment=NewComment('hppa done')))

        bug = self.bz.search(BugQuery.ids([2]))[2]
        self.assertEqual(bug.cc, ('alpha@gentoo.org',))
        self.assertFalse(bug.resolved)
        self.assertEqual(
            self.latest_comment(2, USER_BUGZILLA_USERNAME),
            'hppa done')

    def test_uncc_arch_not_cced(self):
        """Test unCC-ing an arch that is not CC-ed"""
        bug = self.bz.search(BugQuery.ids([3]))[3]
        self.assertEqual(
            bug.cc,
            ('amd64@gentoo.org',),
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.latest_comment(3, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.update(3, BugUpdate(
            status=Status.IN_PROGRESS,
            cc=ListChange.removing('hppa@gentoo.org'),
            comment=NewComment('whut?!')))

        bug = self.bz.search(BugQuery.ids([3]))[3]
        self.assertEqual(bug.cc, ('amd64@gentoo.org',))
        self.assertFalse(bug.resolved)
        self.assertEqual(
            self.latest_comment(3, USER_BUGZILLA_USERNAME),
            'whut?!')

    def test_close(self):
        """Test unCC-ing an arch and closing the bug"""
        bug = self.bz.search(BugQuery.ids([4]))[4]
        self.assertEqual(
            bug.cc,
            ('hppa@gentoo.org',),
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.latest_comment(4, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.update(4, BugUpdate.resolve(
            Resolution.FIXED,
            comment='hppa done\n\nall arches done, closing',
            cc=ListChange.removing('hppa@gentoo.org')))

        bug = self.bz.search(BugQuery.ids([4]))[4]
        self.assertEqual(bug.cc, ())
        self.assertTrue(bug.resolved)
        self.assertEqual(
            self.latest_comment(4, USER_BUGZILLA_USERNAME),
            'hppa done\n\nall arches done, closing')


class SplitDependentBugsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '')
                 }, 1),
            ([], []))

    def test_kwreq(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.KEYWORDREQ, '', depends=[2]),
                 2: mk_bug(BugCategory.KEYWORDREQ, '', depends=[3],
                           blocks=[1]),
                 3: mk_bug(BugCategory.KEYWORDREQ, '', blocks=[2]),
                 }, 1),
            ([2, 3], []))

    def test_streq(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: mk_bug(BugCategory.STABLEREQ, '', depends=[3],
                           blocks=[1]),
                 3: mk_bug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([2, 3], []))

    def test_kwreq_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.KEYWORDREQ, '', depends=[2]),
                 2: mk_bug(BugCategory.STABLEREQ, '', depends=[3],
                           blocks=[1]),
                 3: mk_bug(BugCategory.KEYWORDREQ, '', blocks=[2]),
                 }, 1),
            ([], [2]))

    def test_streq_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: mk_bug(BugCategory.KEYWORDREQ, '', depends=[3],
                           blocks=[1]),
                 3: mk_bug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([], [2]))

    def test_common_dep(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '', depends=[2, 3]),
                 2: mk_bug(BugCategory.STABLEREQ, '', depends=[4],
                           blocks=[1]),
                 3: mk_bug(BugCategory.STABLEREQ, '', depends=[4],
                           blocks=[1]),
                 4: mk_bug(BugCategory.STABLEREQ, '', blocks=[2, 3]),
                 }, 1),
            ([2, 3, 4], []))

    def test_regular(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: mk_bug(None, '', blocks=[1]),
                 }, 1),
            ([], [2]))

    def test_regular_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: mk_bug(BugCategory.STABLEREQ, '', depends=[2, 3]),
                 2: mk_bug(None, '', depends=[4], blocks=[1]),
                 3: mk_bug(BugCategory.STABLEREQ, '', blocks=[1]),
                 4: mk_bug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([3], [2]))
