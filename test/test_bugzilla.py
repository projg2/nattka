""" Tests for Bugzilla interaction. """

import os
import os.path
import unittest

import vcr

from nattka.bugzilla import (NattkaBugzilla, BugCategory, BugInfo,
                             get_combined_buginfo,
                             fill_keywords_from_cc)


API_ENDPOINT = 'https://bugstest.gentoo.org/rest'
# auth data is used only for the initial recording
API_AUTH = os.environ.get('TEST_SERVER_AUTH')
API_KEY = os.environ.get('TEST_API_KEY')

if API_AUTH is not None: # and API_KEY is not None:
    API_AUTH = tuple(API_AUTH.split(':'))
    assert len(API_AUTH) == 2
    RECORD_MODE = 'once'
else:
    RECORD_MODE = 'none'


rec = vcr.VCR(
    cassette_library_dir=os.path.join(os.path.dirname(__file__),
                                      'bugzilla'),
    filter_headers=['Authorization'],
    filter_query_parameters=['Bugzilla_api_key'],
    record_mode=RECORD_MODE,
)


class BugzillaTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY, API_ENDPOINT, API_AUTH)

    @rec.use_cassette()
    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            self.bz.fetch_package_list([560314, 560312, 560316]),
            {560312: BugInfo(BugCategory.KEYWORDREQ,
                             'dev-python/unittest-mixins-1.6\r\n'
                             'dev-python/coverage-4.5.4\r\n',
                             [f'{x}@gentoo.org' for x in ('hppa',
                                                          'm68k',
                                                          'prefix',
                                                          's390',
                                                          'sh',
                                                          'x86')],
                             [500112],
                             []),
             560314: BugInfo(BugCategory.STABLEREQ,
                             'dev-python/mako-1.1.0\r\n',
                             [f'{x}@gentoo.org' for x in ('m68k',
                                                          'sh')],
                             [],
                             []),
             560316: BugInfo(BugCategory.KEYWORDREQ,
                             'dev-python/urllib3-1.25.8\r\n'
                             'dev-python/trustme-0.6.0\r\n'
                             'dev-python/brotlipy-0.7.0\r\n',
                             [f'{x}@gentoo.org' for x in ('hppa',
                                                          'm68k',
                                                          'mips',
                                                          'ppc64',
                                                          'ppc',
                                                          's390',
                                                          'sh',
                                                          'sparc')],
                             [],
                             []),
            })

    @rec.use_cassette()
    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.KEYWORDREQ, limit=3),
            {538510: BugInfo(BugCategory.KEYWORDREQ,
                             '=dev-python/pyzor-1.0.0 \r\n'
                             '=dev-python/gevent-1.0.1\r\n'
                             '=dev-python/greenlet-0.4.11\r\n',
                             ['ia64@gentoo.org', 'ppc@gentoo.org',
                              'sparc@gentoo.org'],
                             [], []),
             548352: BugInfo(BugCategory.KEYWORDREQ,
                             'dev-perl/Class-Load-0.230.0 ~amd64-linux ~arm64 ~m68k ~ppc-aix ~ppc-macos ~s390 ~sh ~x64-macos ~x86-fbsd ~x86-freebsd ~x86-linux ~x86-macos ~x86-solaris\r\n'
                             'dev-perl/Package-Stash-0.370.0 ~amd64-linux\r\n'
                             'dev-perl/Dist-CheckConflicts-0.110.0 ~amd64-linux\r\n'
                             'dev-perl/Package-Stash-XS-0.280.0 ~amd64-linux\r\n'
                             'dev-perl/Test-Requires-0.100.0 ~ppc-aix\r\n',
                             ['arm64@gentoo.org', 'm68k@gentoo.org',
                              'prefix@gentoo.org', 's390@gentoo.org',
                              'sh@gentoo.org', 'sparc@gentoo.org'],
                             [], []),
             560246: BugInfo(BugCategory.KEYWORDREQ,
                             '=media-libs/flac-1.3.2-r1\r\n',
                             ['alpha@gentoo.org', 'amd64@gentoo.org'],
                             [], [])
            })

    @rec.use_cassette()
    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.STABLEREQ, limit=6),
            {541500: BugInfo(BugCategory.STABLEREQ,
                             'app-arch/arj-3.10.22-r7 amd64 ppc x86\r\n',
                             ['maintainer-needed@gentoo.org'],
                             [], []),
             556804: BugInfo(BugCategory.STABLEREQ,
                             'sys-kernel/gentoo-sources-4.1.6\r\n',
                             [], [], []),
             560242: BugInfo(BugCategory.STABLEREQ,
                             '=dev-libs/libebml-1.3.4    hppa amd64\r\n'
                             'media-plugins/vdr-beep-0.1.2 arm hppa\r\n',
                             ['arm@gentoo.org', 'hppa@gentoo.org',
                              'ia64@gentoo.org', 'ppc64@gentoo.org',
                              'sparc@gentoo.org', 'x86@gentoo.org'],
                             [], [560240]),
             560308: BugInfo(BugCategory.STABLEREQ,
                             'dev-python/pytest-5.4.1\r\n',
                             ['amd64@gentoo.org', 'arm64@gentoo.org',
                              'arm@gentoo.org'],
                             [560310], [])
            })


class BugInfoCombinerTest(unittest.TestCase):
    def test_combine_bugs(self):
        """ Test combining linked bugs. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2], []),
                 2: BugInfo('Stabilization', 'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            [], [1])
                }, 1),
            BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n'
                                     'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [], []))

    def test_combine_with_blocker(self):
        """ Test combining stabilization blocked by a regular bug. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2, 3], []),
                 2: BugInfo('Stabilization', 'test/bar-2 x86\r\n',
                            ['x86@gentoo.org'],
                            [3, 4], [1])
                }, 1),
            BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n'
                                     'test/bar-2 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [3, 4], []))

    def test_combine_keywordreq_stablereq(self):
        """ Test combining keywordreq & stablereq. """
        self.assertEqual(
            get_combined_buginfo(
                {1: BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n',
                            ['amd64@gentoo.org', 'x86@gentoo.org'],
                            [2], []),
                 2: BugInfo('Keywording', 'test/foo-1 x86\r\n',
                            ['x86@gentoo.org'],
                            [], [1])
                }, 1),
            BugInfo('Stabilization', 'test/foo-1 amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [2], []))


class KeywordFillerTest(unittest.TestCase):
    def test_fill_keywords_cc(self):
        self.assertEqual(
            fill_keywords_from_cc(
                BugInfo('Stabilization', 'test/foo-1 x86\r\n'
                                         'test/bar-2\r\n'
                                         'test/bar-3 \r\n',
                        ['amd64@gentoo.org', 'x86@gentoo.org'], [], []),
                ['amd64', 'arm64', 'x86']),
            BugInfo('Stabilization', 'test/foo-1 x86\r\n'
                                     'test/bar-2 amd64 x86\r\n'
                                     'test/bar-3  amd64 x86\r\n',
                    ['amd64@gentoo.org', 'x86@gentoo.org'], [], []))
