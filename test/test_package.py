# (c) 2020-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

""" Tests for package processing. """

import os
import shutil
import tempfile
import unittest

from pathlib import Path

from pkgcore.bugzilla import BugCategory
from pkgcore.bugzilla import PackageListError
from pkgcore.ebuild.atom import atom

from test.bug import mk_bug
from nattka.keyword import KEYWORDS_RE
from nattka.package import (add_keywords, check_dependencies,
                            find_repository, package_list_to_json,
                            merge_package_list, expand_package_list,
                            format_results, is_masked,
                            load_profiles, MaskReason)


def get_test_repo(path: Path = Path(__file__).parent):
    conf_path = path / 'conf'
    data_path = path / 'data'
    return find_repository(data_path, conf_path)


class FindRepositoryDomainTests(unittest.TestCase):
    def test_arch(self):
        """Test whether arch is correctly determined."""
        domain, _ = get_test_repo()
        self.assertEqual(domain.arch, 'hppa')


class FindRepositoryUnconfiguredAbsoluteTests(unittest.TestCase):
    def setUp(self):
        top = Path(__file__).parent
        self.conf_path = top / 'conf'
        self.data_path = top / 'data'
        assert self.data_path.is_absolute()

    def do_test(self, path):
        _, r = find_repository(path, self.conf_path)
        self.assertIsNotNone(r)
        self.assertTrue(self.data_path.samefile(r.location))

    def test_top(self):
        self.do_test(self.data_path)

    def test_cat(self):
        self.do_test(self.data_path / 'test')

    def test_pkg(self):
        self.do_test(self.data_path / 'test' / 'amd64-testing')

    def test_profiles(self):
        self.do_test(self.data_path / 'profiles')


class FindRepositoryUnconfiguredRelativeTests(
        FindRepositoryUnconfiguredAbsoluteTests):

    def setUp(self):
        super().setUp()
        self.cwd = Path.cwd()

    def tearDown(self):
        os.chdir(self.cwd)

    def do_test(self, path):
        os.chdir(path)
        _, r = find_repository(Path('.'), self.conf_path)
        self.assertIsNotNone(r)
        self.assertTrue(self.data_path.samefile(r.location))


class FindRepositoryConfiguredAbsoluteTests(
        FindRepositoryUnconfiguredAbsoluteTests):

    def setUp(self):
        super().setUp()

        self.tempdir = tempfile.TemporaryDirectory()
        self.conf_path = Path(self.tempdir.name)
        os.symlink(self.data_path / 'profiles' / 'hppa',
                   self.conf_path / 'make.profile')
        with open(self.conf_path / 'repos.conf', 'w') as f:
            f.write(f'''
[DEFAULT]
main-repo = nattka

[nattka]
location = {self.data_path}
''')

    def tearDown(self):
        self.tempdir.cleanup()


class FindRepositoryConfiguredRelativeTests(
        FindRepositoryConfiguredAbsoluteTests):

    def setUp(self):
        super().setUp()
        self.cwd = Path.cwd()

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def do_test(self, path):
        os.chdir(path)
        _, r = find_repository(Path('.'), self.conf_path)
        self.assertIsNotNone(r)
        self.assertTrue(self.data_path.samefile(r.location))


class FindRepositoryConfiguredSymlinkTests(
        FindRepositoryConfiguredAbsoluteTests):

    def setUp(self):
        super().setUp()
        self.symlinkdir = tempfile.TemporaryDirectory()
        symlink_path = Path(self.symlinkdir.name) / 'symlink'
        os.symlink(self.data_path, symlink_path)
        self.data_path = symlink_path

    def tearDown(self):
        super().tearDown()
        self.symlinkdir.cleanup()


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


class ExpandPackageListTests(BaseRepoTestCase):
    def test_unmodified(self):
        data = '''
            # comment

            # test/amd64-stable-1 *
            test/amd64-testing-1             amd64
            test/amd64-testing-2             amd64 hppa  # *
            test/amd64-stable-hppa-testing-1 hppa
        '''
        self.assertEqual(
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data)),
            data)

    def test_asterisk_streq(self):
        data = '''
            test/mixed-keywords-3    *
            test/mixed-keywords-4    *
            test/amd64-testing-1     *
        '''
        expect = '''
            test/mixed-keywords-3    amd64 hppa
            test/mixed-keywords-4    amd64
            test/amd64-testing-1     -
        '''
        self.assertEqual(
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data)),
            expect)

    def test_asterisk_kwreq(self):
        data = '''
            test/mixed-keywords-4    *
            test/mixed-keywords-9999 *
            test/amd64-stable-1      *
        '''
        expect = '''
            test/mixed-keywords-4    alpha hppa
            test/mixed-keywords-9999 alpha amd64 hppa
            test/amd64-stable-1      -
        '''
        self.assertEqual(
            expand_package_list(self.repo,
                                mk_bug(BugCategory.KEYWORDREQ, data)),
            expect)

    def test_above(self):
        data = '''
            test/amd64-testing-1             amd64

            test/amd64-testing-2             ^ hppa
            # some comment to confuse
            test/amd64-stable-hppa-testing-1 ^
        '''
        expect = '''
            test/amd64-testing-1             amd64

            test/amd64-testing-2             amd64 hppa
            # some comment to confuse
            test/amd64-stable-hppa-testing-1 amd64 hppa
        '''
        self.assertEqual(
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data)),
            expect)

    def test_above_empty(self):
        data = '''
            test/amd64-testing-1
            test/amd64-testing-2             ^
        '''
        expect = f'''
            test/amd64-testing-1
            test/amd64-testing-2             {""}
        '''
        self.assertEqual(
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data)),
            expect)

    def test_above_empty_plus_keywords_left(self):
        data = '''
            test/amd64-testing-1
            test/amd64-testing-2             hppa ^
        '''
        with self.assertRaises(PackageListError):
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data))

    def test_above_empty_plus_keywords_right(self):
        data = '''
            test/amd64-testing-1
            test/amd64-testing-2             ^ hppa
        '''
        with self.assertRaises(PackageListError):
            expand_package_list(self.repo,
                                mk_bug(BugCategory.STABLEREQ, data))


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
            for line in f.readlines():
                m = KEYWORDS_RE.match(line)
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
    maxDiff = None

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
                 'num_profiles': 2,
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
                 'num_profiles': 2,
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
                 'num_profiles': 2,
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


class MergePackageListTests(BaseRepoTestCase):
    def test_disjoint_packages(self):
        self.assertEqual(
            merge_package_list(
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['x86', 'amd64'],
                 },
                {self.get_package('=test/amd64-testing-2'):
                 ['~alpha'],
                 }.items()),
            {self.get_package('=test/amd64-testing-deps-1'):
             ['x86', 'amd64'],
             self.get_package('=test/amd64-testing-2'):
             ['~alpha'],
             })

    def test_disjoint_versions(self):
        self.assertEqual(
            merge_package_list(
                {self.get_package('=test/amd64-testing-1'):
                 ['x86', 'amd64'],
                 },
                {self.get_package('=test/amd64-testing-2'):
                 ['~alpha'],
                 }.items()),
            {self.get_package('=test/amd64-testing-1'):
             ['x86', 'amd64'],
             self.get_package('=test/amd64-testing-2'):
             ['~alpha'],
             })

    def test_disjoint_arches(self):
        self.assertEqual(
            merge_package_list(
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['x86', 'amd64'],
                 },
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['alpha'],
                 }.items()),
            {self.get_package('=test/amd64-testing-deps-1'):
             ['x86', 'amd64', 'alpha'],
             })

    def test_overlapping_arches(self):
        self.assertEqual(
            merge_package_list(
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['x86', 'amd64'],
                 },
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['alpha', 'amd64'],
                 }.items()),
            {self.get_package('=test/amd64-testing-deps-1'):
             ['x86', 'amd64', 'alpha'],
             })

    def test_overlapping_kw_st(self):
        self.assertEqual(
            merge_package_list(
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['~x86', '~amd64'],
                 },
                {self.get_package('=test/amd64-testing-deps-1'):
                 ['alpha', 'amd64'],
                 }.items()),
            {self.get_package('=test/amd64-testing-deps-1'):
             ['~x86', 'alpha', 'amd64'],
             })


class IsAllArchesTests(BaseRepoTestCase):
    def test_allarches(self):
        self.assertTrue(
            self.get_package('=test/amd64-stable-hppa-testing-1')
            .stabilize_allarches)

    def test_not_allarches(self):
        self.assertFalse(
            self.get_package('=test/amd64-stable-1').stabilize_allarches)

    def test_no_metadata_xml(self):
        self.assertFalse(
            self.get_package('=test/amd64-testing-1').stabilize_allarches)

    def test_restrict_match1(self):
        self.assertTrue(
            self.get_package('=test/mixed-keywords-1').stabilize_allarches)

    def test_restrict_mismatch(self):
        self.assertFalse(
            self.get_package('=test/mixed-keywords-3').stabilize_allarches)

    def test_restrict_match2(self):
        self.assertTrue(
            self.get_package('=test/mixed-keywords-9999').stabilize_allarches)


class ResultFormatterTests(BaseRepoTestCase):
    maxDiff = None

    def test_multiple_results(self):
        self.assertEqual(
            list(format_results(sorted(check_dependencies(
                self.repo,
                [(self.get_package('=test/amd64-stable-deps-1'),
                  ['amd64']),
                 (self.get_package('=test/amd64-testing-deps-2'),
                  ['amd64']),
                 (self.get_package('=test/alpha-testing-deps-1'),
                  ['alpha']),
                 ]).output))),
            ['> test/alpha-testing-deps-1',
             '>   rdepend ~alpha stable profile alpha (1 total)',
             '>     test/amd64-testing',
             '> test/amd64-stable-deps-1',
             '>   rdepend amd64 stable profile amd64 (2 total)',
             '>     test/amd64-testing',
             '> test/amd64-testing-deps-2',
             '>   bdepend ~amd64 stable profile amd64 (2 total)',
             '>     test/alpha-testing-deps',
             ])


class IsMaskedTests(BaseRepoTestCase):
    def setUp(self):
        super().setUp()
        self.profiles = load_profiles(self.repo)

    def test_non_masked(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/amd64-stable-hppa-testing-1'),
                ['amd64', 'hppa'],
                self.profiles),
            (MaskReason.NO_MASK, []))

    def test_masked(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/masked-package-1'),
                ['amd64', 'hppa'],
                self.profiles),
            (MaskReason.REPOSITORY_MASK, []))

    def test_profile_masked(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/profile-masked-package-1'),
                ['amd64'],
                self.profiles),
            (MaskReason.PROFILE_MASK, ['amd64']))

    def test_profile_masked_other_profile(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/profile-masked-package-1'),
                ['hppa'],
                self.profiles),
            (MaskReason.NO_MASK, []))

    def test_profile_masked_partially(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/partially-masked-package-1'),
                ['amd64'],
                self.profiles),
            (MaskReason.NO_MASK, []))

    def test_no_profile(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/amd64-testing-1'),
                ['amd64-linux'],
                self.profiles),
            (MaskReason.NO_MASK, []))

    def test_load_profiles(self):
        self.assertEqual(
            sorted((arch,
                    pt.data.path,
                    sorted(str(x) for x in pt.obj.masks),
                    pt.data.status)
                   for arch, profiles in self.profiles.items()
                   for pt in profiles),
            [('alpha', 'alpha', ['test/masked-package'], 'stable'),
             ('amd64', 'amd64',
              ['test/masked-package', 'test/partially-masked-package',
               'test/profile-masked-package'],
              'stable'),
             ('amd64', 'amd64-second',
              ['test/masked-package', 'test/profile-masked-package'],
              'stable'),
             ('hppa', 'hppa', ['test/masked-package'], 'exp'),
             ])

    def test_minus_keyword(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/minus-arch-1'),
                ['amd64', 'hppa'],
                self.profiles),
            (MaskReason.KEYWORD_MASK, ['-hppa']))

    def test_minus_other_keyword(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/minus-arch-1'),
                ['amd64'],
                self.profiles),
            (MaskReason.NO_MASK, []))

    def test_minus_all(self):
        self.assertEqual(
            is_masked(
                self.repo,
                self.get_package('=test/minus-all-1'),
                ['alpha', 'amd64', 'hppa'],
                self.profiles),
            (MaskReason.KEYWORD_MASK, ['-alpha']))
