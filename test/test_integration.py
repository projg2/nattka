""" Integration tests. """

import os.path
import shutil
import tempfile
import unittest

import vcr

from pkgcore.util import parserestrict

from nattka.cli import main

from test import (__path__, get_test_repo)
from test.test_bugzilla import (RECORD_MODE, API_KEY, API_ENDPOINT,
                                API_AUTH_S)


rec = vcr.VCR(
    cassette_library_dir=os.path.join(os.path.dirname(__file__),
                                      'integration'),
    filter_headers=['Authorization'],
    filter_query_parameters=['Bugzilla_api_key'],
    record_mode=RECORD_MODE,
)


class IntegrationTestCase(unittest.TestCase):
    """
    A test case for an integration test.  Combines Bugzilla support
    with a temporary clone of the repository.
    """

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        for subdir in ('conf', 'data'):
            shutil.copytree(os.path.join(__path__[0], subdir),
                            os.path.join(self.tempdir.name, subdir),
                            symlinks=True)

        self.repo = get_test_repo(self.tempdir.name)

        self.common_args = [
            '--bugzilla-endpoint', API_ENDPOINT,
            '--portage-conf', os.path.join(self.tempdir.name, 'conf'),
            '--repo', self.repo.location,
        ]
        if API_AUTH_S is not None and API_KEY is not None:
            self.common_args += [
                '--api-key', API_KEY,
                '--bugzilla-auth', API_AUTH_S,
            ]

    def tearDown(self):
        self.tempdir.cleanup()

    def get_package(self, atom):
        pkg = self.repo.match(parserestrict.parse_match(atom))
        assert len(pkg) == 1
        return pkg[0]


class ApplyTests(IntegrationTestCase):
    @rec.use_cassette()
    def test_apply(self):
        self.assertEqual(
            main(self.common_args + ['apply', '560322']),
            0)
        self.assertEqual(
            self.get_package('=test/amd64-testing-1').keywords,
            ('amd64',))
        self.assertEqual(
            self.get_package('=test/alpha-amd64-hppa-testing-2').keywords,
            ('~alpha', 'amd64', 'hppa'))
