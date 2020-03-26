""" Tests for package processing. """

import os.path
import re
import shutil
import tempfile
import unittest

from pkgcore.util import parserestrict

from nattka.package import (match_package_list, add_keywords,
                            check_dependencies, fill_keywords)

from test import get_test_repo


KEYWORDS_RE = re.compile(r'^KEYWORDS="(.*)"$')


class BaseRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = get_test_repo()

    def get_package(self, atom):
        pkg = self.repo.match(parserestrict.parse_match(atom))
        assert len(pkg) == 1
        return pkg[0]

    def ebuild_path(self, cat, pkg, ver):
        return os.path.join(self.repo.location, cat, pkg,
                            '{}-{}.ebuild'.format(pkg, ver))


class PackageMatcherTests(BaseRepoTestCase):
    def test_versioned_package_list(self):
        """ Test versioned package lists. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
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
            list(((p.path, k) for p, k in match_package_list(
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
                    add_keywords([
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
                    add_keywords([
                        (e1, ['alpha', 'hppa']),
                        (e2, ['amd64']),
                        (e3, ['amd64', 'alpha']),
                    ], stable=True)

                    self.assertEqual(e1.keywords, ('alpha', '~amd64', 'hppa'))
                    self.assertEqual(e2.keywords, ('amd64',))
                    self.assertEqual(e3.keywords, ('alpha', 'amd64', '~hppa'))


def sort_check_result(res):
    return (res.success, sorted(res.output, key=lambda x: x['package']))


class DependencyCheckerTest(BaseRepoTestCase):
    def test_amd64_good(self):
        self.assertEqual(
            check_dependencies(self.repo,
                [(self.get_package('=test/amd64-testing-deps-1'),
                  ['amd64'])]),
            (True, []))

    def test_amd64_bad(self):
        self.assertEqual(
            check_dependencies(self.repo,
                    [(self.get_package('=test/amd64-stable-deps-1'),
                     ['amd64'])]),
            (False, [
                {'__class__': 'NonsolvableDepsInStable',
                 'attr': 'rdepend',
                 'category': 'test',
                 'deps': ['test/amd64-testing'],
                 'keyword': 'amd64',
                 'num_profiles': 1,
                 'package': 'amd64-stable-deps',
                 'profile': 'amd64',
                 'profile_deprecated': False,
                 'profile_status': 'stable',
                 'version': '1'},
            ]))

    def test_alpha_bad(self):
        self.assertEqual(
            check_dependencies(self.repo,
                    [(self.get_package('=test/alpha-testing-deps-1'),
                      ['alpha'])]),
            (False, [
                {'__class__': 'NonsolvableDepsInStable',
                 'attr': 'rdepend',
                 'category': 'test',
                 'deps': ['test/amd64-testing'],
                 'keyword': '~alpha',
                 'num_profiles': 1,
                 'package': 'alpha-testing-deps',
                 'profile': 'alpha',
                 'profile_deprecated': False,
                 'profile_status': 'stable',
                 'version': '1'},
            ]))

    def test_multiple_reports(self):
        self.assertEqual(
            sort_check_result(check_dependencies(self.repo,
                    [(self.get_package('=test/amd64-stable-deps-1'),
                      ['amd64']),
                     (self.get_package('=test/amd64-testing-deps-2'),
                      ['amd64'])
                    ])),
            (False, [
                {'__class__': 'NonsolvableDepsInStable',
                 'attr': 'rdepend',
                 'category': 'test',
                 'deps': ['test/amd64-testing'],
                 'keyword': 'amd64',
                 'num_profiles': 1,
                 'package': 'amd64-stable-deps',
                 'profile': 'amd64',
                 'profile_deprecated': False,
                 'profile_status': 'stable',
                 'version': '1'},
                {'__class__': 'NonsolvableDepsInStable',
                 'attr': 'bdepend',
                 'category': 'test',
                 'deps': ['test/alpha-testing-deps'],
                 'keyword': '~amd64',
                 'num_profiles': 1,
                 'package': 'amd64-testing-deps',
                 'profile': 'amd64',
                 'profile_deprecated': False,
                 'profile_status': 'stable',
                 'version': '2'},
            ]))


class KeywordFillerTest(BaseRepoTestCase):
    def test_fill_keywords_cc(self):
        pkgs = self.repo.match(
            parserestrict.parse_match('test/amd64-testing'))
        inp = [
            (pkgs[0], ['alpha']),
            (pkgs[1], []),
        ]
        self.assertEqual(list(fill_keywords(self.repo, inp,
                                            [f'{x}@gentoo.org'
                                             for x in ('alpha', 'hppa')])),
                         [
                             (pkgs[0], ['alpha']),
                             (pkgs[1], ['alpha', 'hppa']),
                         ])
