""" Tests for package processing. """

import os.path
import unittest

import nattka.package

from test import get_test_repo


class PackageMatcherTests(unittest.TestCase):
    def setUp(self):
        self.repo = get_test_repo()

    def ebuild_path(self, cat, pkg, ver):
        return os.path.join(self.repo.location, cat, pkg,
                            '{}-{}.ebuild'.format(pkg, ver))

    def test_versioned_package_list(self):
        """ Test versioned package lists. """
        self.assertEqual(
            list(((p.path, k) for p, k in nattka.package.match_package_list(
                self.repo, '''
                    test/amd64-testing-1
                    test/amd64-testing-2
                    test/amd64-stable-hppa-testing-1
                '''))), [
                (self.ebuild_path('test', 'amd64-testing', '1'), []),
                (self.ebuild_path('test', 'amd64-testing', '2'), []),
                (self.ebuild_path('test', 'amd64-stable-hppa-testing', '1'), []),
            ])

    def test_versioned_package_list_with_keywords(self):
        """ Test versioned package lists with keywords. """
        self.assertEqual(
            list(((p.path, k) for p, k in nattka.package.match_package_list(
                self.repo, '''
                    test/amd64-testing-1 amd64 hppa
                    test/amd64-testing-2 ~hppa ~alpha
                    test/amd64-stable-hppa-testing-1
                '''))), [
                (self.ebuild_path('test', 'amd64-testing', '1'),
                 ['amd64', 'hppa']),
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['hppa', 'alpha']),
                (self.ebuild_path('test', 'amd64-stable-hppa-testing', '1'),
                 []),
            ])
