# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for Bugzilla interaction. """

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


class BugzillaTestCase(unittest.TestCase):
    """
    TestCase subclass initiating Bugzilla as its 'bz' parameter.
    """

    bz: NattkaBugzilla

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY, API_ENDPOINT)


class BugzillaTests(BugzillaTestCase):
    maxDiff = None

    @rec.use_cassette()
    def test_whoami(self):
        """ Test whoami(). """
        self.assertEqual(self.bz.whoami(), BUGZILLA_USERNAME)

    @rec.use_cassette()
    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            self.bz.fetch_package_list([2, 3, 4]),
            {2: BugInfo(BugCategory.KEYWORDREQ,
                        'dev-python/unittest-mixins-1.6\r\n'
                        'dev-python/coverage-4.5.4\r\n',
                        [f'{x}@gentoo.org' for x in ('alpha',
                                                     'hppa')],
                        [1], [], True),
             3: BugInfo(BugCategory.STABLEREQ,
                        'dev-python/mako-1.1.0 amd64\r\n',
                        [f'{x}@gentoo.org' for x in ('amd64',)],
                        [7], [], False),
             4: BugInfo(BugCategory.KEYWORDREQ,
                        'dev-python/urllib3-1.25.8\r\n'
                        'dev-python/trustme-0.6.0\r\n'
                        'dev-python/brotlipy-0.7.0\r\n',
                        [f'{x}@gentoo.org' for x in ('hppa',)],
                        [], [], None),
             })

    @rec.use_cassette()
    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(
            self.bz.find_bugs(BugCategory.KEYWORDREQ),
            {2: BugInfo(BugCategory.KEYWORDREQ,
                        'dev-python/unittest-mixins-1.6\r\n'
                        'dev-python/coverage-4.5.4\r\n',
                        [f'{x}@gentoo.org' for x in ('alpha',
                                                     'hppa')],
                        [1], [], True),
             4: BugInfo(BugCategory.KEYWORDREQ,
                        'dev-python/urllib3-1.25.8\r\n'
                        'dev-python/trustme-0.6.0\r\n'
                        'dev-python/brotlipy-0.7.0\r\n',
                        [f'{x}@gentoo.org' for x in ('hppa',)],
                        [], [], None),
             })

    @rec.use_cassette()
    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(
            self.bz.find_bugs(BugCategory.STABLEREQ),
            {3: BugInfo(BugCategory.STABLEREQ,
                        'dev-python/mako-1.1.0 amd64\r\n',
                        [f'{x}@gentoo.org' for x in ('amd64',)],
                        [7], [], False),
             5: BugInfo(BugCategory.STABLEREQ,
                        'app-arch/arj-3.10.22-r7 amd64 hppa\r\n',
                        ['test@example.com'],
                        [], [], None),
             6: BugInfo(BugCategory.STABLEREQ,
                        'sys-kernel/gentoo-sources-4.1.6\r\n',
                        [], [], [], None),
             7: BugInfo(BugCategory.STABLEREQ,
                        'dev-python/pytest-5.4.1\r\n',
                        [],
                        [], [3], None)
             })

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
            self.bz.fetch_package_list([2])[2].sanity_check,
            True)

    @rec.use_cassette()
    def test_set_status_and_comment(self):
        """ Test setting sanity-check status and commenting. """
        self.bz.update_status(3, False, 'sanity check failed!\r\n')
        self.assertEqual(
            self.bz.fetch_package_list([3])[3].sanity_check,
            False)
        self.assertEqual(
            self.bz.get_latest_comment(3, BUGZILLA_USERNAME),
            'sanity check failed!')

    @rec.use_cassette()
    def test_reset_status(self):
        """ Test resetting sanity-check status. """
        self.bz.update_status(4, None)
        self.assertEqual(
            self.bz.fetch_package_list([4])[4].sanity_check,
            None)


class BugInfoCombinerTest(unittest.TestCase):
    def test_combine_bugs(self):
        """ Test combining linked bugs. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2], [], True),
                 2: BugInfo(BugCategory.STABLEREQ,
                            'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            [], [1], True)
                 }, 1),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [], [],
                    True))

    def test_combine_with_blocker(self):
        """ Test combining stabilization blocked by a regular bug. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2, 3], [], True),
                 2: BugInfo(BugCategory.STABLEREQ,
                            'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            [3, 4], [1], True)
                 }, 1),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [3, 4], [],
                    True))

    def test_combine_keywordreq_stablereq(self):
        """ Test combining keywordreq & stablereq. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo(BugCategory.STABLEREQ,
                            'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2], [], True),
                 2: BugInfo(BugCategory.KEYWORDREQ,
                            'test/foo-1 x86\r\n',
                            ['x86@gentoo.org'],
                            [], [1], True)
                 }, 1),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [2], [],
                    True))


class KeywordFillerTest(unittest.TestCase):
    def test_fill_keywords_cc(self):
        """ Test that missing keywords are copied from CC. """

        self.assertEqual(
            update_keywords_from_cc(
                BugInfo(BugCategory.STABLEREQ,
                        'test/foo-1 x86\r\n'
                        'test/bar-2\r\n'
                        'test/bar-3 \r\n',
                        ['amd64@gentoo.org', 'x86@gentoo.org'], [], [],
                        None),
                ['amd64', 'arm64', 'x86']),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 x86\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [], [],
                    None))

    def test_filter_keywords_cc(self):
        """ Test filtering keywords based on CC. """

        self.assertEqual(
            update_keywords_from_cc(
                BugInfo(BugCategory.STABLEREQ,
                        'test/foo-1 amd64 x86 arm\r\n'
                        'test/bar-2 amd64 x86\r\n'
                        'test/bar-3 arm\r\n',
                        ['amd64@gentoo.org', 'x86@gentoo.org'], [], [],
                        None),
                ['amd64', 'arm64', 'x86']),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86\r\n'
                    'test/bar-2 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [], [],
                    None))

    def test_no_cc(self):
        """
        Test that packages are not dropped if no arches are CC-ed
        and no keywords are provided.
        """

        self.assertEqual(
            update_keywords_from_cc(
                BugInfo(BugCategory.STABLEREQ,
                        'test/foo-1 amd64 x86 arm\r\n'
                        'test/bar-2 amd64 x86\r\n'
                        'test/bar-3\r\n',
                        [], [], [],
                        None),
                ['amd64', 'arm64', 'x86']),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 amd64 x86 arm\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3\r\n',
                    [], [], [],
                    None))

    def test_fill_keywords_cc_no_email(self):
        """
        Test filling keywords from CC containing only login parts
        of e-mail addresses (i.e. obtained without API key).
        """

        self.assertEqual(
            update_keywords_from_cc(
                BugInfo(BugCategory.STABLEREQ,
                        'test/foo-1 x86\r\n'
                        'test/bar-2\r\n'
                        'test/bar-3 \r\n',
                        ['amd64', 'x86'], [], [],
                        None),
                ['amd64', 'arm64', 'x86']),
            BugInfo(BugCategory.STABLEREQ,
                    'test/foo-1 x86\r\n'
                    'test/bar-2 amd64 x86\r\n'
                    'test/bar-3 amd64 x86\r\n',
                    ['amd64', 'x86'], [], [],
                    None))
