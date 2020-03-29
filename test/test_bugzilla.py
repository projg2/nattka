""" Tests for Bugzilla interaction. """

import os
import os.path
import unittest

import vcr

from nattka.bugzilla import (NattkaBugzilla, BugCategory, BugInfo,
                             get_combined_buginfo)


# API key should be needed only for the initial recording
API_KEY = os.environ.get('TEST_API_KEY', 'no-api-key')


rec = vcr.VCR(
    cassette_library_dir=os.path.join(os.path.dirname(__file__),
                                      'bugzilla'),
    filter_query_parameters=['Bugzilla_api_key'],
)


class BugzillaTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY)

    @rec.use_cassette()
    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            self.bz.fetch_package_list([700194, 711762, 710410]),
            {700194: (BugCategory.KEYWORDREQ,
                      'dev-python/unittest-mixins-1.6\r\n'
                      'dev-python/coverage-4.5.4\r\n',
                      [f'{x}@gentoo.org' for x in ('hppa',
                                                   'm68k',
                                                   'prefix',
                                                   's390',
                                                   'sh',
                                                   'x86')],
                      [701196],
                      []),
             711762: (BugCategory.KEYWORDREQ,
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
             710410: (BugCategory.STABLEREQ,
                      'dev-python/mako-1.1.0\r\n',
                      [f'{x}@gentoo.org' for x in ('m68k',
                                                   'sh')],
                      [],
                      []),
            })

    @rec.use_cassette()
    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.KEYWORDREQ, limit=3),
            {254398: (BugCategory.KEYWORDREQ,
                      'app-dicts/aspell-de-alt-2.1.1-r1\r\n',
                      [f'{x}@gentoo.org' for x in ('app-dicts+disabled',
                                                   'm68k')],
                      [],
                      []),
             468854: (BugCategory.KEYWORDREQ,
                      'app-arch/lrzip-0.631-r1\r\n',
                      [f'{x}@gentoo.org' for x in ('mgorny',
                                                   'proxy-maint',
                                                   's390',
                                                   'sh')],
                      [],
                      [465684, 458184]),
             481722: (BugCategory.KEYWORDREQ,
                      'dev-libs/mathjax-2.7.4\r\n',
                      [f'{x}@gentoo.org' for x in ('prefix',)],
                      [],
                      [481462])
            })

    @rec.use_cassette()
    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.STABLEREQ, limit=10),
                         {522930: (BugCategory.STABLEREQ,
                                   '=sys-kernel/gentoo-sources-3.4.113\r\n',
                                   [f'{x}@gentoo.org' for x in ('chutzpah',
                                                                'cluster',
                                                                'dlan',
                                                                'kernel',
                                                                'pacho',
                                                                'security-kernel')],
                                   [],
                                   [469854, 512526, 524848, 568212,
                                    464546, 579076]),
                          543310: (BugCategory.STABLEREQ,
                                   '=dev-util/diffball-1.0.1-r2\r\n',
                                   [f'{x}@gentoo.org' for x in ('dev-portage',
                                                                'ferringb',
                                                                'mgorny')],
                                   [],
                                   [])
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
