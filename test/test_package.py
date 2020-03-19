""" Tests for package processing. """

import os.path
import re
import shutil
import tempfile
import unittest

import nattka.package

from test import get_test_repo


KEYWORDS_RE = re.compile(r'^KEYWORDS="(.*)"$')


class BaseRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = get_test_repo()

    def ebuild_path(self, cat, pkg, ver):
        return os.path.join(self.repo.location, cat, pkg,
                            '{}-{}.ebuild'.format(pkg, ver))


class PackageMatcherTests(BaseRepoTestCase):
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


class DuplicatedEbuild(object):
    """
    Fake ebuild object.  Duplicates original ebuild contents
    for the purpose of testing.
    """

    def __init__(self, orig_path):
        self.f = tempfile.NamedTemporaryFile('w+')
        with open(orig_path, 'r') as orig_ebuild:
            shutil.copyfileobj(orig_ebuild, self.f)
        self.f.flush()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.f.close()

    @property
    def path(self):
        return self.f.name

    @property
    def keywords(self):
        self.f.seek(0)
        for l in self.f.readlines():
            m = KEYWORDS_RE.match(l)
            if m:
                return tuple(m.group(1).split())


class KeywordAdderTest(BaseRepoTestCase):
    def test_keyword(self):
        """ Test keywording ebuilds. """
        with DuplicatedEbuild(
                self.ebuild_path('test', 'amd64-testing', '1')) as e1:
            with DuplicatedEbuild(self.ebuild_path(
                    'test', 'amd64-testing', '2')) as e2:
                with DuplicatedEbuild(self.ebuild_path(
                        'test', 'amd64-stable-hppa-testing', '1')) as e3:
                    nattka.package.add_keywords([
                        (e1, ['alpha', 'hppa']),
                        (e2, ['amd64']),
                        (e3, ['amd64', 'alpha']),
                    ], stable=False)

                    self.assertEqual(e1.keywords, ('~alpha', '~amd64', '~hppa'))
                    self.assertEqual(e2.keywords, ('~amd64',))
                    self.assertEqual(e3.keywords, ('~alpha', '~amd64', '~hppa'))

    def test_stabilize(self):
        """ Test stabilizing ebuilds. """
        with DuplicatedEbuild(
                self.ebuild_path('test', 'amd64-testing', '1')) as e1:
            with DuplicatedEbuild(self.ebuild_path(
                    'test', 'amd64-testing', '2')) as e2:
                with DuplicatedEbuild(self.ebuild_path(
                        'test', 'amd64-stable-hppa-testing', '1')) as e3:
                    nattka.package.add_keywords([
                        (e1, ['alpha', 'hppa']),
                        (e2, ['amd64']),
                        (e3, ['amd64', 'alpha']),
                    ], stable=True)

                    self.assertEqual(e1.keywords, ('alpha', '~amd64', 'hppa'))
                    self.assertEqual(e2.keywords, ('amd64',))
                    self.assertEqual(e3.keywords, ('alpha', 'amd64', '~hppa'))
