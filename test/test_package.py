# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for package processing. """

import re
import shutil
import tempfile
import unittest

from pathlib import Path

from pkgcore.ebuild.atom import atom

from nattka.package import (match_package_list, add_keywords,
                            check_dependencies, PackageNoMatch,
                            KeywordNoMatch, PackageInvalid)

from test import get_test_repo


KEYWORDS_RE = re.compile(r'^KEYWORDS="(.*)"$')


class BaseRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = get_test_repo()

    def get_package(self, spec):
        pkg = self.repo.match(atom(spec))
        assert len(pkg) == 1
        return pkg[0]

    def ebuild_path(self, cat, pkg, ver):
        return str(Path(self.repo.location) / cat / pkg /
                   f'{pkg}-{ver}.ebuild')


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

    def test_versioned_package_list_equals(self):
        """ Test versioned package lists using = syntax. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, '''
                    test/amd64-testing-1
                    =test/amd64-testing-2
                '''))), [
                (self.ebuild_path('test', 'amd64-testing', '1'), []),
                (self.ebuild_path('test', 'amd64-testing', '2'), []),
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

    def test_invalid_spec(self):
        """ Test package list containing invalid dependency spec. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        <>test/amd64-testing-2 amd64 hppa
                    '''):
                pass

    def test_noequals_spec(self):
        """ Test package list containing dependency spec other than =. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        >=test/amd64-testing-2 amd64 hppa
                    '''):
                pass

    def test_equals_wildcard_spec(self):
        """ Test package list containing =...* spec. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-2* amd64 hppa
                    '''):
                pass

    def test_pure_catpkg_spec(self):
        """
        Test package list containing just the category and package name.
        """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        test/amd64-testing amd64 hppa
                    '''):
                pass

    def test_pure_package_spec(self):
        """ Test package list containing just the package name. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        amd64-testing amd64 hppa
                    '''):
                pass

    def test_wildcard_package_spec(self):
        """ Test package list using wildcards. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        test/amd64-* amd64 hppa
                    '''):
                pass

    def test_blocker_package_spec(self):
        """ Test package list using a blocker. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        !=test/amd64-testing-1 amd64 hppa
                    '''):
                pass

    def test_slotted_package_spec(self):
        """ Test package list using a slot. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:0 amd64 hppa
                    '''):
                pass

    def test_useflags_package_spec(self):
        """ Test package list including a USE dependency. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1[foo] amd64 hppa
                    '''):
                pass

    def test_repo_package_spec(self):
        """ Test package list including a repository name. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1::foo amd64 hppa
                    '''):
                pass

    def test_no_match(self):
        """ Test package list containing package with no matches. """
        with self.assertRaises(PackageNoMatch):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-1 amd64 hppa
                        test/enoent-7
                    '''):
                pass

    def test_unknown_keywords(self):
        """ Test package list containing unknown keywords. """
        with self.assertRaises(KeywordNoMatch):
            for m in match_package_list(self.repo, '''
                        test/amd64-testing-1 amd64 hppa
                        test/amd64-testing-2 mysuperarch
                    '''):
                pass


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
                    self.assertEqual(e3.keywords, ('~alpha', 'amd64', '~hppa'))

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


def results_to_dict(res):
    """
    Convert pkgcheck NonSolvableDeps* result into dicts for checking.
    """

    out = []
    for r in sorted(res.output, key=lambda r: r.package):
        out.append({
            '__class__': r.name,
            'attr': r.attr,
            'category': r.category,
            'deps': list(r.deps),
            'keyword': r.keyword,
            'num_profiles': r.num_profiles,
            'package': r.package,
            'profile': r.profile,
            'profile_deprecated': r.profile_deprecated,
            'profile_status': r.profile_status,
            'version': r.version,
        })

    return (res.success, out)


class DependencyCheckerTest(BaseRepoTestCase):
    def test_amd64_good(self):
        self.assertEqual(
            check_dependencies(self.repo,
                [(self.get_package('=test/amd64-testing-deps-1'),
                  ['amd64'])]),
            (True, []))

    def test_amd64_bad(self):
        self.assertEqual(
            results_to_dict(check_dependencies(self.repo,
                    [(self.get_package('=test/amd64-stable-deps-1'),
                     ['amd64'])])),
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
            results_to_dict(check_dependencies(self.repo,
                    [(self.get_package('=test/alpha-testing-deps-1'),
                      ['alpha'])])),
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
            results_to_dict(check_dependencies(self.repo,
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
