# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for Bugzilla interaction. """

import typing
import unittest

from pathlib import Path

import vcr

from nattka.bugzilla import (NattkaBugzilla, BugCategory, BugInfo,
                             get_combined_buginfo,
                             update_keywords_from_cc)


API_ENDPOINT = 'http://127.0.0.1:33113/rest'
API_KEY = 'xH3pICxBPtyhTrFjvuuzIaNYek9uqisCJzR9izAZ'
BUGZILLA_USERNAME = 'nattka' + '@gentoo.org'

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
            resolved: bool = False
            ) -> BugInfo:
    return BugInfo(category,
                   security,
                   atoms,
                   cc,
                   depends,
                   blocks,
                   sanity_check,
                   resolved)


class BugzillaTestCase(unittest.TestCase):
    """
    TestCase subclass initiating Bugzilla as its 'bz' parameter.
    """

    bz: NattkaBugzilla

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY, API_ENDPOINT)


class BugzillaTests(BugzillaTestCase):
    maxDiff = None

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
                           sanity_check=False),
                4: makebug(BugCategory.KEYWORDREQ,
                           'dev-python/urllib3-1.25.8\r\n'
                           'dev-python/trustme-0.6.0\r\n'
                           'dev-python/brotlipy-0.7.0\r\n',
                           [f'{x}@gentoo.org' for x in ('hppa',)]),
                5: makebug(BugCategory.STABLEREQ,
                           'app-arch/arj-3.10.22-r7 amd64 hppa\r\n',
                           ['test@example.com'],
                           security=True),
                6: makebug(BugCategory.STABLEREQ,
                           'sys-kernel/gentoo-sources-4.1.6\r\n',
                           security=True),
                7: makebug(BugCategory.STABLEREQ,
                           'dev-python/pytest-5.4.1\r\n',
                           blocks=[3]),
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
            self.get_bugs([3, 5, 6, 7]))

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
            self.get_bugs([3, 7]))

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

    @rec.use_cassette()
    def test_set_status(self):
        """ Test setting sanity-check status. """
        self.bz.update_status(2, True)
        self.assertEqual(
            self.bz.find_bugs([2])[2].sanity_check,
            True)

    @rec.use_cassette()
    def test_set_status_and_comment(self):
        """ Test setting sanity-check status and commenting. """
        self.bz.update_status(3, False, 'sanity check failed!\r\n')
        self.assertEqual(
            self.bz.find_bugs([3])[3].sanity_check,
            False)
        self.assertEqual(
            self.bz.get_latest_comment(3, BUGZILLA_USERNAME),
            'sanity check failed!')

    @rec.use_cassette()
    def test_reset_status(self):
        """ Test resetting sanity-check status. """
        self.bz.update_status(4, None)
        self.assertEqual(
            self.bz.find_bugs([4])[4].sanity_check,
            None)


class makebugCombinerTest(unittest.TestCase):
    def test_combine_bugs(self):
        """ Test combining linked bugs. """
        self.assertEqual(
            get_combined_buginfo(
                {1: makebug(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            depends=[2],
                            sanity_check=True),
                 2: makebug(BugCategory.STABLEREQ,
                            'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            blocks=[1],
                            sanity_check=True)
                 }, 1),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'],
                    sanity_check=True))

    def test_combine_with_blocker(self):
        """ Test combining stabilization blocked by a regular bug. """
        self.assertEqual(
            get_combined_buginfo(
                {1: makebug(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            depends=[2, 3],
                            sanity_check=True),
                 2: makebug(BugCategory.STABLEREQ,
                            'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            depends=[3, 4],
                            blocks=[1],
                            sanity_check=True)
                 }, 1),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'],
                    depends=[3, 4],
                    sanity_check=True))

    def test_combine_keywordreq_stablereq(self):
        """ Test combining keywordreq & stablereq. """
        self.assertEqual(
            get_combined_buginfo(
                {1: makebug(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            depends=[2],
                            security=True,
                            sanity_check=True),
                 2: makebug(BugCategory.KEYWORDREQ,
                            'test/foo-1 x86\r\n',
                            ['x86@gentoo.org'],
                            blocks=[1],
                            sanity_check=True)
                 }, 1),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'],
                    depends=[2],
                    security=True,
                    sanity_check=True))

    def test_combine_bugs_resolved(self):
        """ Test (not) combining with resolved bugs. """
        self.assertEqual(
            get_combined_buginfo(
                {1: makebug(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            depends=[2],
                            sanity_check=True),
                 2: makebug(BugCategory.STABLEREQ,
                            'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            blocks=[1],
                            resolved=True,
                            sanity_check=True)
                 }, 1),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'],
                    depends=[2],
                    sanity_check=True))


class KeywordFillerTest(unittest.TestCase):
    def test_fill_keywords_cc(self):
        """ Test that missing keywords are copied from CC. """

        self.assertEqual(
            update_keywords_from_cc(
                makebug(BugCategory.STABLEREQ,
                        'test/foo-1 x86\r\n'
                        'test/bar-2\r\n'
                        'test/bar-3 \r\n',
                        ['amd64@gentoo.org', 'x86@gentoo.org']),
                ['amd64', 'arm64', 'x86']),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 x86\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org']))

    def test_filter_keywords_cc(self):
        """ Test filtering keywords based on CC. """

        self.assertEqual(
            update_keywords_from_cc(
                makebug(BugCategory.STABLEREQ,
                        'test/foo-1 amd64 x86 arm\r\n'
                        'test/bar-2 amd64 x86\r\n'
                        'test/bar-3 arm\r\n',
                        ['amd64@gentoo.org', 'x86@gentoo.org']),
                ['amd64', 'arm64', 'x86']),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org']))

    def test_no_cc(self):
        """
        Test that packages are not dropped if no arches are CC-ed
        and no keywords are provided.
        """

        self.assertEqual(
            update_keywords_from_cc(
                makebug(BugCategory.STABLEREQ,
                        'test/foo-1 amd64 x86 arm\r\n'
                        'test/bar-2 amd64 x86\r\n'
                        'test/bar-3\r\n'),
                ['amd64', 'arm64', 'x86']),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86 arm\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3\r\n'))

    def test_fill_keywords_cc_no_email(self):
        """
        Test filling keywords from CC containing only login parts
        of e-mail addresses (i.e. obtained without API key).
        """

        self.assertEqual(
            update_keywords_from_cc(
                makebug(BugCategory.STABLEREQ,
                        'test/foo-1 x86\r\n'
                        'test/bar-2\r\n'
                        'test/bar-3 \r\n',
                        ['amd64', 'x86']),
                ['amd64', 'arm64', 'x86']),
            makebug(BugCategory.STABLEREQ,
                    'test/foo-1 x86\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3 amd64 x86\r\n',
                    ['amd64', 'x86']))
