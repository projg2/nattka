""" Tests for Bugzilla interaction. """

import os
import os.path
import unittest

import vcr

from nattka.bugzilla import NattkaBugzilla, BugCategory, BugInfo


# API key should be needed only for the initial recording
API_KEY = os.environ.get('TEST_API_KEY', 'no-api-key')


def strip_api_key(request):
    request.body = request.body.replace(API_KEY.encode(),
                                        b'<!-- API key stripped -->')
    return request


rec = vcr.VCR(
    before_record_request=strip_api_key,
    cassette_library_dir=os.path.join(os.path.dirname(__file__),
                                      'bugzilla'),
)


class BugzillaTests(unittest.TestCase):
    @rec.use_cassette()
    def setUp(self):
        self.bz = NattkaBugzilla(API_KEY)

    @rec.use_cassette()
    def test_fetch_bugs(self):
        """ Test getting simple bugs. """
        self.assertEqual(
            list(self.bz.fetch_package_list([700194, 711762, 710410])),
            [(BugCategory.KEYWORDREQ,
              'dev-python/unittest-mixins-1.6\r\n'
              'dev-python/coverage-4.5.4\r\n',
              {'x86', 'sh', 'm68k', 'hppa', 's390'},
              [701196],
              []),
             (BugCategory.KEYWORDREQ,
              'dev-python/urllib3-1.25.8\r\n'
              'dev-python/trustme-0.6.0\r\n'
              'dev-python/brotlipy-0.7.0\r\n',
              {'ppc', 'sh', 'ppc64', 'sparc', 'm68k', 'hppa', 'mips',
               's390'},
              [],
              []),
             (BugCategory.STABLEREQ,
              'dev-python/mako-1.1.0\r\n',
              {'sh', 'm68k'},
              [],
              []),
            ])

    @rec.use_cassette()
    def test_find_keywordreqs(self):
        """ Test finding keywordreqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.KEYWORDREQ, limit=3),
            {254398: (BugCategory.KEYWORDREQ,
                      'app-dicts/aspell-de-alt-2.1.1-r1\r\n',
                      {'m68k'},
                      [],
                      []),
             468854: (BugCategory.KEYWORDREQ,
                      'app-arch/lrzip-0.631-r1\r\n',
                      {'sh', 's390'},
                      [],
                      [465684, 458184]),
             481722: (BugCategory.KEYWORDREQ,
                      'dev-libs/mathjax-2.7.4\r\n',
                      set(),
                      [],
                      [481462])
            })

    @rec.use_cassette()
    def test_find_stablereqs(self):
        """ Test finding stablereqs. """
        self.assertEqual(self.bz.find_bugs(BugCategory.STABLEREQ, limit=10),
                         {522930: (BugCategory.STABLEREQ,
                                   '=sys-kernel/gentoo-sources-3.4.113\r\n',
                                   set(),
                                   [],
                                   [469854, 512526, 524848, 568212,
                                    464546, 579076]),
                          543310: (BugCategory.STABLEREQ,
                                   '=dev-util/diffball-1.0.1-r2\r\n',
                                   set(),
                                   [],
                                   [])
                         })
