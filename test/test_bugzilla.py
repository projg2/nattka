# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for Bugzilla interaction. """

import typing
import unittest

from pathlib import Path

import vcr

from nattka.bugzilla import (NattkaBugzilla, BugCategory, BugInfo,
                             arches_from_cc, split_dependent_bugs)


API_ENDPOINT = 'http://127.0.0.1:33113/rest'
API_KEY = 'xH3pICxBPtyhTrFjvuuzIaNYek9uqisCJzR9izAZ'
USER_API_KEY = 'dhaGUYKZOGGVRmg4k24wEXaWRHntUjIlW6eqePu1'
BUGZILLA_USERNAME = 'nattka' + '@gentoo.org'
USER_BUGZILLA_USERNAME = 'test@example.com'

rec = vcr.VCR(
    cassette_library_dir=str(Path(__file__).parent / 'bugzilla'),
    filter_query_parameters=['Bugzilla_api_key'],
    record_mode='once',
)


def makebug(category: typing.Optional[BugCategory],
            atoms: str,
            cc: typing.List[str] = [],
            depends: typing.List[int] = [],
            blocks: typing.List[int] = [],
            sanity_check: typing.Optional[bool] = None,
            security: bool = False,
            resolved: bool = False,
            keywords: typing.List[str] = [],
            whiteboard: str = ''
            ) -> BugInfo:
    return BugInfo(category,
                   security,
                   atoms,
                   cc,
                   depends,
                   blocks,
                   sanity_check,
                   resolved,
                   keywords,
                   whiteboard)


class BugzillaTests(unittest.TestCase):
    bz: NattkaBugzilla
    maxDiff = None

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY, API_ENDPOINT)

    def get_bugs(self,
                 req: typing.Iterable[int]
                 ) -> typing.Dict[int, BugInfo]:
        """Return expected data for specified bugs"""
        bugs = {1: makebug(None, '\r\n', blocks=[2]),
                2: makebug(BugCategory.KEYWORDREQ,
                           'dev-python/unittest-mixins-1.6\r\n'
                           'dev-python/coverage-4.5.4\r\n',
                           [f'{x}@gentoo.org' for x in ('alpha',
                                                        'hppa')],
                           depends=[1],
                           blocks=[9],
                           sanity_check=True),
                3: makebug(BugCategory.STABLEREQ,
                           'dev-python/mako-1.1.0 amd64\r\n',
                           [f'{x}@gentoo.org' for x in ('amd64',)],
                           depends=[7],
                           keywords=['STABLEREQ'],
                           sanity_check=False),
                4: makebug(BugCategory.KEYWORDREQ,
                           'dev-python/urllib3-1.25.8\r\n'
                           'dev-python/trustme-0.6.0\r\n'
                           'dev-python/brotlipy-0.7.0\r\n',
                           [f'{x}@gentoo.org' for x in ('hppa',)],
                           keywords=['KEYWORDREQ']),
                5: makebug(BugCategory.STABLEREQ,
                           'app-arch/arj-3.10.22-r7 amd64 hppa\r\n',
                           ['test@example.com'],
                           whiteboard='test whiteboard',
                           security=True),
                6: makebug(BugCategory.STABLEREQ,
                           'sys-kernel/gentoo-sources-4.1.6\r\n',
                           security=True),
                7: makebug(BugCategory.STABLEREQ,
                           'dev-python/pytest-5.4.1\r\n',
                           blocks=[3],
                           keywords=['ALLARCHES']),
                8: makebug(BugCategory.STABLEREQ,
                           'dev-lang/python-3.7.7\r\n',
                           resolved=True),
                9: makebug(BugCategory.KEYWORDREQ,
                           'dev-python/frobnicate-11\r\n',
                           depends=[2]),
                }
        for k in list(bugs):
            if k not in req:
                del bugs[k]
        return bugs

    @rec.use_cassette()
    def test_whoami(self):
        """ Test whoami(). """
        self.assertEqual(self.bz.whoami(), BUGZILLA_USERNAME)

    @rec.use_cassette()
    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            self.bz.find_bugs([1, 2, 3, 4, 8]),
            self.get_bugs([1, 2, 3, 4, 8]))

    @rec.use_cassette()
    def test_fetch_bugs_keywordreq(self):
        """Test getting and filtering to keywordreqs."""
        self.assertEqual(
            self.bz.find_bugs([1, 2, 3, 4, 8],
                              category=[BugCategory.KEYWORDREQ]),
            self.get_bugs([2, 4]))

    @rec.use_cassette()
    def test_fetch_bugs_stablereq(self):
        """Test getting and filtering to stablereqs."""
        self.assertEqual(
            self.bz.find_bugs([1, 2, 3, 4, 8],
                              category=[BugCategory.STABLEREQ]),
            self.get_bugs([3, 8]))

    @rec.use_cassette()
    def test_fetch_bugs_any(self):
        """Test getting and filtering to keywordreqs and stablereqs."""
        self.assertEqual(
            self.bz.find_bugs([1, 2, 3, 4, 8],
                              category=[BugCategory.KEYWORDREQ,
                                        BugCategory.STABLEREQ]),
            self.get_bugs([2, 3, 4, 8]))

    @rec.use_cassette()
    def test_fetch_bugs_security(self):
        """Test getting and filtering to security bugs."""
        self.assertEqual(
            self.bz.find_bugs([3, 4, 6, 8],
                              security=True),
            self.get_bugs([6]))

    @rec.use_cassette()
    def test_fetch_sanity_check_passed(self):
        """Test filtering bugs by sanity-check+."""
        self.assertEqual(
            self.bz.find_bugs(bugs=[2, 3, 4, 6],
                              sanity_check=[True]),
            self.get_bugs([2]))

    @rec.use_cassette()
    def test_fetch_sanity_check_failed(self):
        """Test filtering bugs by sanity-check-."""
        self.assertEqual(
            self.bz.find_bugs(bugs=[2, 3, 4, 6],
                              sanity_check=[False]),
            self.get_bugs([3]))

    @rec.use_cassette()
    def test_fetch_sanity_check_both(self):
        """Test filtering bugs by sanity-check+/-."""
        self.assertEqual(
            self.bz.find_bugs(bugs=[2, 3, 4, 6],
                              sanity_check=[True, False]),
            self.get_bugs([2, 3]))

    @rec.use_cassette()
    def test_fetch_bugs_cc(self):
        """Test filtering bugs by CC."""
        self.assertEqual(
            self.bz.find_bugs([1, 3, 4, 8],
                              cc=['hppa@gentoo.org']),
            self.get_bugs([4]))

    @rec.use_cassette()
    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.KEYWORDREQ]),
            self.get_bugs([2, 4, 9]))

    @rec.use_cassette()
    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.STABLEREQ]),
            self.get_bugs([3, 5, 6, 7, 8]))

    @rec.use_cassette()
    def test_find_security(self):
        """ Test finding security bugs. """
        self.assertEqual(
            self.bz.find_bugs(security=True),
            self.get_bugs([5, 6]))

    @rec.use_cassette()
    def test_find_security_keywordreq(self):
        """ Test finding security keywordreq bugs (no such thing). """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.KEYWORDREQ],
                              security=True),
            {})

    @rec.use_cassette()
    def test_find_security_stablereq(self):
        """ Test finding security stablereq bugs (all of them). """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.STABLEREQ],
                              security=True),
            self.get_bugs([5, 6]))

    @rec.use_cassette()
    def test_find_security_both(self):
        """ Test finding security keywordreq and stablereq bugs. """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.KEYWORDREQ,
                                        BugCategory.STABLEREQ],
                              security=True),
            self.get_bugs([5, 6]))

    @rec.use_cassette()
    def test_find_nonsecurity_keywordreqs(self):
        """ Test finding keywordreqs that are not security bugs. """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.KEYWORDREQ],
                              security=False),
            self.get_bugs([2, 4, 9]))

    @rec.use_cassette()
    def test_find_nonsecurity_stablereqs(self):
        """ Test finding non-security stablereqs. """
        self.assertEqual(
            self.bz.find_bugs(category=[BugCategory.STABLEREQ],
                              security=False),
            self.get_bugs([3, 7, 8]))

    @rec.use_cassette()
    def test_find_bugs_cc(self):
        """Test finding bugs by CC."""
        self.assertEqual(
            self.bz.find_bugs(cc=['hppa@gentoo.org']),
            self.get_bugs([2, 4]))

    @rec.use_cassette()
    def test_find_sanity_check_passed(self):
        """Test finding bugs that are flagged sanity-check+."""
        self.assertEqual(
            self.bz.find_bugs(sanity_check=[True]),
            self.get_bugs([2]))

    @rec.use_cassette()
    def test_find_sanity_check_failed(self):
        """Test finding bugs that are flagged sanity-check-."""
        self.assertEqual(
            self.bz.find_bugs(sanity_check=[False]),
            self.get_bugs([3]))

    @rec.use_cassette()
    def test_find_sanity_check_both(self):
        """Test finding bugs that are flagged sanity-check+ or -."""
        self.assertEqual(
            self.bz.find_bugs(sanity_check=[True, False]),
            self.get_bugs([2, 3]))

    @rec.use_cassette()
    def test_find_bugs_personal_tags(self):
        """Test finding bugs by personal tags."""
        self.assertEqual(
            self.bz.find_bugs(skip_tags=['nattka:skip']),
            self.get_bugs([1, 2, 4, 5, 6, 7, 8, 9]))

    @rec.use_cassette()
    def test_find_bugs_unresolved(self):
        """Test finding unresolved bugs"""
        self.assertEqual(
            self.bz.find_bugs(unresolved=True),
            self.get_bugs([1, 2, 3, 4, 5, 6, 7, 9]))

    @rec.use_cassette()
    def test_resolve_dependencies(self):
        """Test resolving missing dependencies recursively"""
        bz = self.bz.find_bugs([9])
        self.assertEqual(
            self.bz.resolve_dependencies(bz),
            self.get_bugs([1, 2, 9]))

    @rec.use_cassette()
    def test_get_latest_comment(self):
        """ Test getting latest self-comment. """
        self.assertEqual(
            self.bz.get_latest_comment(3, BUGZILLA_USERNAME),
            'sanity check failed!')


class DestructiveBugzillaTests(unittest.TestCase):
    bz: NattkaBugzilla
    maxDiff = None

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY, API_ENDPOINT)

    @rec.use_cassette()
    def test_set_status(self):
        """Test setting sanity-check status"""
        self.assertIsNone(
            self.bz.find_bugs([5])[5].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(5, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(5, True)

        self.assertTrue(
            self.bz.find_bugs([5])[5].sanity_check)
        self.assertIsNone(
            self.bz.get_latest_comment(5, BUGZILLA_USERNAME))

    @rec.use_cassette()
    def test_set_status_and_comment(self):
        """Test setting sanity-check status and commenting"""
        self.assertIsNone(
            self.bz.find_bugs([6])[6].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(6, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(6, False, 'sanity check failed!\r\n')

        self.assertFalse(
            self.bz.find_bugs([6])[6].sanity_check)
        self.assertEqual(
            self.bz.get_latest_comment(6, BUGZILLA_USERNAME),
            'sanity check failed!')

    @rec.use_cassette()
    def test_reset_status(self):
        """Test resetting sanity-check status"""
        self.assertTrue(
            self.bz.find_bugs([2])[2].sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(2, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(2, None)

        self.assertIsNone(
            self.bz.find_bugs([2])[2].sanity_check)
        self.assertIsNone(
            self.bz.get_latest_comment(2, BUGZILLA_USERNAME))

    @rec.use_cassette()
    def test_set_status_and_cc(self):
        bug = self.bz.find_bugs([6])[6]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.cc,
            [],
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(6, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(6, True, cc_add=['amd64@gentoo.org',
                                               'hppa@gentoo.org'])

        bug = self.bz.find_bugs([6])[6]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.cc, ['amd64@gentoo.org', 'hppa@gentoo.org'])
        self.assertIsNone(
            self.bz.get_latest_comment(6, BUGZILLA_USERNAME))

    @rec.use_cassette()
    def test_set_status_and_add_keywords(self):
        bug = self.bz.find_bugs([8])[8]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.keywords,
            [],
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(8, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(8, True, keywords_add=['ALLARCHES'])

        bug = self.bz.find_bugs([8])[8]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.keywords, ['ALLARCHES'])
        self.assertIsNone(
            self.bz.get_latest_comment(8, BUGZILLA_USERNAME))

    @rec.use_cassette()
    def test_set_status_and_remove_keywords(self):
        bug = self.bz.find_bugs([7])[7]
        self.assertIsNone(
            bug.sanity_check,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            bug.keywords,
            ['ALLARCHES'],
            'Bugzilla instance tainted, please reset')
        self.assertIsNone(
            self.bz.get_latest_comment(7, BUGZILLA_USERNAME),
            'Bugzilla instance tainted, please reset')

        self.bz.update_status(7, True, keywords_remove=['ALLARCHES'])

        bug = self.bz.find_bugs([7])[7]
        self.assertTrue(bug.sanity_check)
        self.assertEqual(bug.keywords, [])
        self.assertIsNone(
            self.bz.get_latest_comment(7, BUGZILLA_USERNAME))


class DestructiveUserBugzillaTests(unittest.TestCase):
    bz: NattkaBugzilla
    maxDiff = None

    def setUp(self):
        self.bz = NattkaBugzilla(USER_API_KEY, API_ENDPOINT)

    @rec.use_cassette()
    def test_uncc_arch(self):
        """Test unCC-ing an arch from a bug without closing it"""
        bug = self.bz.find_bugs([2])[2]
        self.assertEqual(
            bug.cc,
            ['alpha@gentoo.org', 'hppa@gentoo.org'],
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.bz.get_latest_comment(2, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.resolve_bug(2, ['hppa@gentoo.org'], 'hppa done')

        bug = self.bz.find_bugs([2])[2]
        self.assertEqual(bug.cc, ['alpha@gentoo.org'])
        self.assertFalse(bug.resolved)
        self.assertEqual(
            self.bz.get_latest_comment(2, USER_BUGZILLA_USERNAME),
            'hppa done')

    @rec.use_cassette()
    def test_uncc_arch_not_cced(self):
        """Test unCC-ing an arch that is not CC-ed"""
        bug = self.bz.find_bugs([3])[3]
        self.assertEqual(
            bug.cc,
            ['amd64@gentoo.org'],
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.bz.get_latest_comment(3, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.resolve_bug(3, ['hppa@gentoo.org'], 'whut?!')

        bug = self.bz.find_bugs([3])[3]
        self.assertEqual(bug.cc, ['amd64@gentoo.org'])
        self.assertFalse(bug.resolved)
        self.assertEqual(
            self.bz.get_latest_comment(3, USER_BUGZILLA_USERNAME),
            'whut?!')

    @rec.use_cassette()
    def test_close(self):
        """Test unCC-ing an arch and closing the bug"""
        bug = self.bz.find_bugs([4])[4]
        self.assertEqual(
            bug.cc,
            ['hppa@gentoo.org'],
            'Bugzilla instance tainted, please reset')
        self.assertFalse(
            bug.resolved,
            'Bugzilla instance tainted, please reset')
        self.assertEqual(
            self.bz.get_latest_comment(4, USER_BUGZILLA_USERNAME),
            '',  # initial comment
            'Bugzilla instance tainted, please reset')

        self.bz.resolve_bug(4,
                            ['hppa@gentoo.org'],
                            'hppa done\n\nall arches done, closing',
                            resolve=True)

        bug = self.bz.find_bugs([4])[4]
        self.assertEqual(bug.cc, [])
        self.assertTrue(bug.resolved)
        self.assertEqual(
            self.bz.get_latest_comment(4, USER_BUGZILLA_USERNAME),
            'hppa done\n\nall arches done, closing')


class ArchesFromCCTest(unittest.TestCase):
    def test_email(self):
        self.assertEqual(
            arches_from_cc(['amd64@gentoo.org', 'x86@gentoo.org'],
                           ['amd64', 'arm64', 'x86']),
            ['amd64', 'x86'])

    def test_email_extra(self):
        self.assertEqual(
            arches_from_cc(['amd64@gentoo.org', 'example@gentoo.org',
                            'x86@example.com'],
                           ['amd64', 'arm64', 'x86']),
            ['amd64'])

    def test_no_email(self):
        self.assertEqual(
            arches_from_cc(['amd64', 'x86'],
                           ['amd64', 'arm64', 'x86']),
            ['amd64', 'x86'])

    def test_no_email_extra(self):
        self.assertEqual(
            arches_from_cc(['amd64', 'example', 'x86'],
                           ['amd64', 'arm64', 'x86']),
            ['amd64', 'x86'])


class SplitDependentBugsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '')
                 }, 1),
            ([], []))

    def test_kwreq(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.KEYWORDREQ, '', depends=[2]),
                 2: makebug(BugCategory.KEYWORDREQ, '', depends=[3],
                            blocks=[1]),
                 3: makebug(BugCategory.KEYWORDREQ, '', blocks=[2]),
                 }, 1),
            ([2, 3], []))

    def test_streq(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: makebug(BugCategory.STABLEREQ, '', depends=[3],
                            blocks=[1]),
                 3: makebug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([2, 3], []))

    def test_kwreq_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.KEYWORDREQ, '', depends=[2]),
                 2: makebug(BugCategory.STABLEREQ, '', depends=[3],
                            blocks=[1]),
                 3: makebug(BugCategory.KEYWORDREQ, '', blocks=[2]),
                 }, 1),
            ([], [2]))

    def test_streq_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: makebug(BugCategory.KEYWORDREQ, '', depends=[3],
                            blocks=[1]),
                 3: makebug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([], [2]))

    def test_common_dep(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '', depends=[2, 3]),
                 2: makebug(BugCategory.STABLEREQ, '', depends=[4],
                            blocks=[1]),
                 3: makebug(BugCategory.STABLEREQ, '', depends=[4],
                            blocks=[1]),
                 4: makebug(BugCategory.STABLEREQ, '', blocks=[2, 3]),
                 }, 1),
            ([2, 3, 4], []))

    def test_regular(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '', depends=[2]),
                 2: makebug(None, '', blocks=[1]),
                 }, 1),
            ([], [2]))

    def test_regular_mixed(self):
        self.assertEqual(
            split_dependent_bugs(
                {1: makebug(BugCategory.STABLEREQ, '', depends=[2, 3]),
                 2: makebug(None, '', depends=[4], blocks=[1]),
                 3: makebug(BugCategory.STABLEREQ, '', blocks=[1]),
                 4: makebug(BugCategory.STABLEREQ, '', blocks=[2]),
                 }, 1),
            ([3], [2]))
