# (c) 2020-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

""" Package processing support. """

import enum
import itertools
import typing
from pathlib import Path

import pkgcheck
from pkgcheck.results import Result

try:
    from pkgcheck.checks.visibility import NonsolvableDeps
except ImportError:
    from pkgcheck.checks.visibility import _NonsolvableDeps as NonsolvableDeps

import pkgcore.ebuild.domain
import pkgcore.ebuild.ebuild_src
from pkgcore.bugzilla import Bug, BugCategory
from pkgcore.ebuild.keywording import select_best_version, suggested_keywords
from pkgcore.ebuild.misc import sort_keywords
from pkgcore.config import load_config
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.profiles import OnDiskProfile
from pkgcore.ebuild.repo_objs import _KnownProfile
from pkgcore.ebuild.repository import UnconfiguredTree
from nattka.keyword import update_keywords_in_file


class RepoTuple(typing.NamedTuple):
    domain: pkgcore.ebuild.domain.domain
    repo: UnconfiguredTree


PackageKeywordsIterable = (
    typing.Iterable[typing.Tuple[pkgcore.ebuild.ebuild_src.package,
                                 typing.List[str]]])

PackageKeywordsDict = (
    typing.Dict[pkgcore.ebuild.ebuild_src.package, typing.List[str]])


class ProfileTuple(typing.NamedTuple):
    data: _KnownProfile
    obj: OnDiskProfile


ProfileIterable = typing.Iterable[ProfileTuple]


ProfileDict = typing.Mapping[str, ProfileIterable]


class CheckResult(typing.NamedTuple):
    success: bool
    output: typing.List[Result]


class MaskReason(enum.Enum):
    NO_MASK = enum.auto()
    REPOSITORY_MASK = enum.auto()
    PROFILE_MASK = enum.auto()
    KEYWORD_MASK = enum.auto()


def find_repository(path: Path,
                    conf_path: typing.Optional[Path] = None
                    ) -> RepoTuple:
    """
    Find an ebuild repository in specified `path`.

    Find an ebuild repository in specified `path`, and return initiated
    a tuple of (domain, repo object).  If `conf_path` is specified,
    it overrides config location.
    """
    c = load_config(
        location=str(conf_path) if conf_path is not None else None)
    domain = c.get_default('domain')

    # if it's a configured repository, we need to handle it explicitly
    # started with longest paths in case of nested repos
    for repo in reversed(sorted(domain.ebuild_repos_raw,
                                key=lambda x: len(x.location))):
        p = path
        while not p.samefile(p / '..'):
            if p.samefile(repo.location):
                return RepoTuple(domain, repo)
            p = p / '..'

    # fallback to unconfigured repo search
    return RepoTuple(domain, domain.find_repo(str(path),
                                              config=c,
                                              configure=False))


def expand_package_list(repo: UnconfiguredTree,
                        bug: Bug,
                        ) -> str:
    """
    Expand `*` and `^` entries in package list

    `repo` is the repository, `bug` is the original bug to work on.
    Returns new package list contents.

    Note that this function assumes that Bug.match_packages() has been
    called already, and did not raise any exceptions, i.e. that the bug
    is known to have a valid package list.

    Raises PackageListError if a `^` cannot be resolved unambiguously.
    """

    stable = bug.category == BugCategory.STABLEREQ

    def suggest(pkg: atom) -> typing.List[str]:
        best = select_best_version(repo.match(pkg))
        assert best is not None
        return sort_keywords(suggested_keywords(repo, best, stable=stable))

    return str(bug.package_list.expand(suggest))


def add_keywords(tuples: PackageKeywordsIterable,
                 stable: bool
                 ) -> None:
    """
    Add testing (stable=False) or stable (stable=True) keywords to
    ebuilds, as specified by package-keyword tuples.
    """

    for p, keywords in tuples:
        update_keywords_in_file(p.path, keywords, stable=stable)


def check_dependencies(repo: UnconfiguredTree,
                       tuples: PackageKeywordsIterable,
                       profiles: str = "stable,dev",
                       ) -> CheckResult:
    """
    Check whether dependencies are satisfied for package-arch @tuples,
    in @repo.  Returns a pair of (boolean status, error list).

    @profiles specifies the list of profiles to check, and is passed
    through to pkgcheck as the `-p` option.
    """

    errors = []
    ret = True

    for keywords, packages in itertools.groupby(tuples, lambda x: x[1]):
        package_strs = list((str(x[0].versioned_atom) for x in packages))
        results = pkgcheck.scan(['-c', 'VisibilityCheck',
                                 '-p', profiles,
                                 '-a', ','.join(keywords),
                                 '-r', repo.location,
                                 ] + package_strs)

        results = list(results)
        for r in results:
            if r.name.startswith('NonsolvableDeps'):
                # workaround a bug (or feature?) in pkgcheck-0.8*
                # that causes the checks to be done against all versions
                pkgstr = f'={r.category}/{r.package}-{r.version}'
                if pkgstr not in package_strs:
                    continue
                ret = False
                errors.append(r)

    return CheckResult(ret, errors)


def package_list_to_json(tuples: PackageKeywordsIterable
                         ) -> typing.Dict[str, typing.List[str]]:
    """
    Return JSON-friendly dict of package list
    """

    return {k.cpvstr: sort_keywords(v) for k, v in tuples}


def merge_package_list(dest: PackageKeywordsDict,
                       other: PackageKeywordsIterable
                       ) -> PackageKeywordsDict:
    """
    Merge package list `other` into `dest` and return `dest`
    """

    for pkg, keywords in other:
        newkw = dest.setdefault(pkg, [])
        for k in keywords:
            while f'~{k}' in newkw:
                # upgrade from ~arch to stable
                newkw.remove(f'~{k}')
            if k not in newkw:
                newkw.append(k)

    return dest


def result_group_key(r: NonsolvableDeps) -> tuple:
    """Key used to group pkgcheck results"""
    return (r.category, r.package, r.version)


def result_sort_key(r: NonsolvableDeps) -> tuple:
    """Key used to sort pkgcheck results"""
    return (r.category, r.package, r.version,
            r.keyword, r.attr, r.profile)


def format_results(issues: typing.Iterable[Result]
                   ) -> typing.Iterator[str]:
    """
    Format pkgcheck results `issues` and yield list of result lines
    """
    for r in issues:
        assert isinstance(r, NonsolvableDeps)
    for key, values in itertools.groupby(
            issues,
            key=result_group_key):
        yield f'> {key[0]}/{key[1]}-{key[2]}'
        for r in sorted(values, key=result_sort_key):
            profile_status = ('deprecated ' if r.profile_deprecated
                              else '')
            profile_status += r.profile_status
            num_profiles = (f' ({r.num_profiles} total)'
                            if r.num_profiles is not None else '')
            yield (f'>   {r.attr} {r.keyword} {profile_status} '
                   f'profile {r.profile}{num_profiles}')
            for d in sorted(r.deps):
                yield f'>     {d}'


def is_masked(repo: UnconfiguredTree,
              pkg: pkgcore.ebuild.ebuild_src.package,
              keywords: typing.Iterable[str],
              profiles: ProfileDict
              ) -> typing.Tuple[MaskReason, typing.List[str]]:
    """
    Return whether package `pkg` is masked for all `keywords`

    Check whether `pkg` is entirely masked in `repo` for specified
    `keywords`.  `profiles` is the dict returned by `load_profiles()`.

    Return a tuple consisting of the mask reason and a list
    of applicable keywords (if any).  MaskReason.NO_MASK is returned
    if the package is not masked.
    """

    masked_kws = set()
    for k in pkg.keywords:
        if k == '-*':
            masked_kws = set(keywords)
        elif k.startswith('-'):
            masked_kws.add(k.lstrip('-'))
        else:
            # in case we had '-*'
            masked_kws.discard(k.lstrip('~'))
    masked_kws.intersection_update(keywords)
    if masked_kws:
        return (MaskReason.KEYWORD_MASK,
                sorted(f'-{k}' for k in masked_kws))

    for m in repo.masked:
        if m.match(pkg):
            return (MaskReason.REPOSITORY_MASK, [])

    for k in keywords:
        k_profs = profiles.get(k, [])
        if not k_profs:
            continue
        for pt in k_profs:
            # profile masks include repo masks, so deduplicate
            for m in pt.obj.masks.difference(repo.masked):
                if m.match(pkg):
                    break
            else:
                # if no match, break outer loop as we have at least
                # one unmasked
                break
        else:
            # all profiles masked the package
            masked_kws.add(k)

    if masked_kws:
        return (MaskReason.PROFILE_MASK, sorted(masked_kws))
    return (MaskReason.NO_MASK, [])


def load_profiles(repo: UnconfiguredTree
                  ) -> ProfileDict:
    """
    Load all profiles from the repository

    Return a mapping of a keyword to the list of profile tuples.
    Each tuple consists of the profile data (from ``profiles.desc``)
    and an initialized profile object.
    """

    def key(pt: ProfileTuple) -> str:
        return pt.obj.arch

    return dict(
        (arch, sorted(profiles)) for arch, profiles
        in itertools.groupby(
            sorted((ProfileTuple(p, OnDiskProfile(p.base, p.path))
                    for p in repo.profiles),
                   key=key),
            key=key))
