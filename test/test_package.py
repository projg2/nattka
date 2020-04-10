# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for package processing. """

import shutil
import tempfile
import unittest

from pathlib import Path

from pkgcore.ebuild.atom import atom

from nattka.bugzilla import BugCategory
from nattka.keyword import KEYWORDS_RE
from nattka.package import (match_package_list, add_keywords,
                            check_dependencies, PackageNoMatch,
                            KeywordNoMatch, PackageInvalid,
                            find_repository, select_best_version,
                            package_list_to_json)

from test.test_bugzilla import makebug


def get_test_repo(path: Path = Path(__file__).parent):
    conf_path = path / 'conf'
    data_path = path / 'data'
    return find_repository(data_path, conf_path)


class FindRepositoryTests(unittest.TestCase):
    def test_arch(self):
        """Test whether arch is correctly determined."""
        domain, _ = get_test_repo()
        self.assertEqual(domain.arch, 'hppa')


class BaseRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = get_test_repo().repo

    def get_package(self, spec):
        pkg = self.repo.match(atom(spec))
        assert len(pkg) == 1
        return pkg[0]

    def ebuild_path(self, cat, pkg, ver):
        return str(Path(self.repo.location) / cat / pkg
                                            / f'{pkg}-{ver}.ebuild')


class BestVersionSelectorTests(BaseRepoTestCase):
    def test_live(self):
        """Test that live ebuild is ignored"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-9999'),
                self.get_package('=test/amd64-testing-2'),
                self.get_package('=test/amd64-testing-1'),
            ]).cpvstr,
            'test/amd64-testing-2')

    def test_live_only(self):
        """Test choice between live ebuilds"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-9998'),
                self.get_package('=test/amd64-testing-9999'),
            ]).cpvstr,
            'test/amd64-testing-9999')

    def test_unkeyworded(self):
        """Test that unkeyworded ebuild is ignored"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-1'),
                self.get_package('=test/amd64-testing-10'),
                self.get_package('=test/amd64-testing-2'),
            ]).cpvstr,
            'test/amd64-testing-2')

    def test_unkeyworded_only(self):
        """Test choice between unkeyworded ebuilds"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-10'),
                self.get_package('=test/amd64-testing-20'),
            ]).cpvstr,
            'test/amd64-testing-20')

    def test_live_and_unkeyworded(self):
        """Test that both live and unkeyworded ebuilds are ignored"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-1'),
                self.get_package('=test/amd64-testing-9999'),
                self.get_package('=test/amd64-testing-10'),
                self.get_package('=test/amd64-testing-2'),
            ]).cpvstr,
            'test/amd64-testing-2')

    def test_live_and_unkeyworded_only(self):
        """Test that choice between live and unkeyworded ebuilds"""
        self.assertEqual(
            select_best_version([
                self.get_package('=test/amd64-testing-9999'),
                self.get_package('=test/amd64-testing-20'),
                self.get_package('=test/amd64-testing-10'),
                self.get_package('=test/amd64-testing-9998'),
            ]).cpvstr,
            'test/amd64-testing-20')


class PackageMatcherTests(BaseRepoTestCase):
    def test_versioned_package_list(self):
        """ Test versioned package lists. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/amd64-testing-1
                    test/amd64-testing-2
                    test/amd64-stable-hppa-testing-1
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '1'), []),
                (self.ebuild_path('test', 'amd64-testing', '2'), []),
                (self.ebuild_path(
                    'test', 'amd64-stable-hppa-testing', '1'),
                    []),
            ])

    def test_versioned_package_list_equals(self):
        """ Test versioned package lists using = syntax. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/amd64-testing-1
                    =test/amd64-testing-2
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '1'), []),
                (self.ebuild_path('test', 'amd64-testing', '2'), []),
            ])

    def test_versioned_package_list_with_keywords(self):
        """ Test versioned package lists with keywords. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/amd64-testing-1 amd64 hppa
                    test/amd64-testing-2 ~hppa ~alpha
                    test/amd64-stable-hppa-testing-1
                ''')]))), [
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
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        <>test/amd64-testing-2 amd64 hppa
                    ''')]):
                pass

    def test_noequals_spec(self):
        """ Test package list containing dependency spec other than =. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        >=test/amd64-testing-2 amd64 hppa
                    ''')]):
                pass

    def test_noequals_spec_kwreq(self):
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        >=test/amd64-stable-hppa-testing-1 hppa
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa']),
                (self.ebuild_path('test', 'amd64-stable-hppa-testing', '2'),
                 ['hppa']),
            ])

    def test_equals_wildcard_spec(self):
        """ Test package list containing =...* spec. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-2* amd64 hppa
                    ''')]):
                pass

    def test_equals_wildcard_spec_kwreq(self):
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        =test/amd64-testing-2* amd64 hppa
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa']),
            ])

    def test_pure_catpkg_spec(self):
        """
        Test package list containing just the category and package name.
        """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        test/amd64-testing amd64 hppa
                    ''')]):
                pass

    def test_pure_catpkg_spec_kwreq(self):
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing amd64 hppa
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa']),
            ])

    def test_pure_package_spec(self):
        """ Test package list containing just the package name. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        amd64-testing amd64 hppa
                    ''')]):
                pass

    def test_pure_package_spec_kwreq(self):
        """ Test package list containing just the package name. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        amd64-testing amd64 hppa
                    ''')]):
                pass

    def test_wildcard_package_spec(self):
        """ Test package list using wildcards. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        test/amd64-* amd64 hppa
                    ''')]):
                pass

    def test_wildcard_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        test/amd64-* amd64 hppa
                    ''')]):
                pass

    def test_blocker_package_spec(self):
        """ Test package list using a blocker. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        !=test/amd64-testing-1 amd64 hppa
                    ''')]):
                pass

    def test_slotted_package_spec(self):
        """ Test package list using a slot. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:0 amd64 hppa
                    ''')]):
                pass

    def test_slotted_package_spec_kwreq(self):
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing:0 amd64 hppa
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa']),
            ])

    def test_slot_slotop_eq_package_spec(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:= amd64 hppa
                    ''')]):
                pass

    def test_slot_slotop_eq_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:0= amd64 hppa
                    ''')]):
                pass

    def test_slotop_eq_package_spec(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:0= amd64 hppa
                    ''')]):
                pass

    def test_slotop_eq_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:= amd64 hppa
                    ''')]):
                pass

    def test_slotop_any_package_spec(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:* amd64 hppa
                    ''')]):
                pass

    def test_slotop_any_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:* amd64 hppa
                    ''')]):
                pass

    def test_subslot_package_spec(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1:0/0 amd64 hppa
                    ''')]):
                pass

    def test_subslot_package_spec_kwreq(self):
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing:0/0 amd64 hppa
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa']),
            ])

    def test_useflags_package_spec(self):
        """ Test package list including a USE dependency. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1[foo] amd64 hppa
                    ''')]):
                pass

    def test_useflags_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1[foo] amd64 hppa
                    ''')]):
                pass

    def test_repo_package_spec(self):
        """ Test package list including a repository name. """
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1::foo amd64 hppa
                    ''')]):
                pass

    def test_repo_package_spec_kwreq(self):
        with self.assertRaises(PackageInvalid):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                        test/amd64-testing-2 amd64 hppa
                        =test/amd64-testing-1::foo amd64 hppa
                    ''')]):
                pass

    def test_no_match(self):
        """ Test package list containing package with no matches. """
        with self.assertRaises(PackageNoMatch):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-1 amd64 hppa
                        test/enoent-7
                    ''')]):
                pass

    def test_unknown_keywords(self):
        """ Test package list containing unknown keywords. """
        with self.assertRaises(KeywordNoMatch):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-1 amd64 hppa
                        test/amd64-testing-2 mysuperarch
                    ''')]):
                pass

    def test_previous_keywords(self):
        """Test use of ^ token to copy previous keywords"""
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/amd64-testing-1 amd64 hppa
                    test/amd64-testing-2 ^ alpha
                    test/amd64-stable-hppa-testing-1 ^
                ''')]))), [
                (self.ebuild_path('test', 'amd64-testing', '1'),
                 ['amd64', 'hppa']),
                (self.ebuild_path('test', 'amd64-testing', '2'),
                 ['amd64', 'hppa', 'alpha']),
                (self.ebuild_path('test', 'amd64-stable-hppa-testing', '1'),
                 ['amd64', 'hppa', 'alpha']),
            ])

    def test_previous_keywords_on_first_line(self):
        with self.assertRaises(KeywordNoMatch):
            for m in match_package_list(
                    self.repo, [makebug(BugCategory.STABLEREQ, '''
                        test/amd64-testing-1 ^ alpha
                        test/amd64-testing-2 amd64 hppa
                    ''')]):
                pass

    def test_asterisk_kwreq(self):
        """Test use of * token to rekeyword existing"""
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.KEYWORDREQ, '''
                    test/mixed-keywords-4 *
                ''')]))), [
                (self.ebuild_path('test', 'mixed-keywords', '4'),
                 ['alpha', 'hppa']),
            ])

    def test_asterisk_streq(self):
        """Test use of * token to stabilize existing"""
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/mixed-keywords-3 *
                ''')]))), [
                (self.ebuild_path('test', 'mixed-keywords', '3'),
                 ['amd64', 'hppa']),
            ])

    def test_asterisk_streq_limited(self):
        """Test use of * token to stabilize existing with less ~arch"""
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/mixed-keywords-4 *
                ''')]))), [
                (self.ebuild_path('test', 'mixed-keywords', '4'),
                 ['amd64']),
            ])

    def test_fill_keywords_cc(self):
        """Test that missing keywords are copied from CC"""
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/mixed-keywords-4
                ''', ['amd64@gentoo.org', 'hppa@gentoo.org',
                      'example@gentoo.org'])]))), [
                (self.ebuild_path('test', 'mixed-keywords', '4'),
                 ['amd64', 'hppa']),
            ])

    def test_filter_keywords_cc(self):
        """ Test filtering keywords based on CC. """
        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/mixed-keywords-4 amd64 hppa
                ''', ['amd64@gentoo.org'])]))), [
                (self.ebuild_path('test', 'mixed-keywords', '4'),
                 ['amd64']),
            ])

    def test_fill_keywords_cc_no_email(self):
        """
        Test filling keywords from CC containing only login parts
        of e-mail addresses (i.e. obtained without API key)
        """

        self.assertEqual(
            list(((p.path, k) for p, k in match_package_list(
                self.repo, [makebug(BugCategory.STABLEREQ, '''
                    test/mixed-keywords-4
                ''', ['amd64', 'hppa', 'example'])]))), [
                (self.ebuild_path('test', 'mixed-keywords', '4'),
                 ['amd64', 'hppa']),
            ])


class FakeEbuild(object):
    """
    Fake ebuild object.  Duplicates original ebuild contents
    for the purpose of testing.
    """

    def __init__(self, path: Path):
        self.path = path

    @property
    def keywords(self):
        with open(self.path, 'r') as f:
            for l in f.readlines():
                m = KEYWORDS_RE.match(l)
                if m:
                    return tuple(m.group('keywords').split())


class KeywordAdderTest(BaseRepoTestCase):
    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        shutil.copytree(self.repo.location,
                        Path(self.tempdir.name) / 'data')

    def tearDown(self):
        self.tempdir.cleanup()

    def ebuild_path(self, cat, pkg, ver):
        return str(Path(self.tempdir.name) / 'data' / cat / pkg
                                           / f'{pkg}-{ver}.ebuild')

    def test_keyword(self):
        """ Test keywording ebuilds. """
        e1 = FakeEbuild(self.ebuild_path('test', 'amd64-testing', '1'))
        e2 = FakeEbuild(self.ebuild_path('test', 'amd64-testing', '2'))
        e3 = FakeEbuild(
            self.ebuild_path('test', 'amd64-stable-hppa-testing', '1'))

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
        e1 = FakeEbuild(self.ebuild_path('test', 'amd64-testing', '1'))
        e2 = FakeEbuild(self.ebuild_path('test', 'amd64-testing', '2'))
        e3 = FakeEbuild(
            self.ebuild_path('test', 'amd64-stable-hppa-testing', '1'))

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
            check_dependencies(
                self.repo,
                [(self.get_package('=test/amd64-testing-deps-1'),
                  ['amd64'])]),
            (True, []))

    def test_amd64_bad(self):
        self.assertEqual(
            results_to_dict(check_dependencies(
                self.repo,
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
            results_to_dict(check_dependencies(
                self.repo,
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
            results_to_dict(check_dependencies(
                self.repo,
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


class PackageListToJSONTests(BaseRepoTestCase):
    def test_basic(self):
        self.assertEqual(
            package_list_to_json(
                [(self.get_package('=test/amd64-testing-deps-1'),
                  ['x86', 'amd64']),
                 (self.get_package('=test/amd64-testing-2'),
                  []),
                 ]),
            {'test/amd64-testing-deps-1': ['amd64', 'x86'],
             'test/amd64-testing-2': [],
             })
