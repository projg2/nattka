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
