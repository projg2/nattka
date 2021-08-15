# (c) 2020 Michał Górny
# 2-clause BSD license

""" Package processing support. """

import enum
import itertools
import re
import typing

from pathlib import Path

import lxml.etree

import pkgcheck
from pkgcheck.results import Result
try:
    from pkgcheck.checks.visibility import NonsolvableDeps
except ImportError:
    from pkgcheck.checks.visibility import _NonsolvableDeps as NonsolvableDeps

import pkgcore.ebuild.domain
import pkgcore.ebuild.ebuild_src
from pkgcore.config import load_config
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.errors import MalformedAtom
from pkgcore.ebuild.profiles import OnDiskProfile
from pkgcore.ebuild.repo_objs import _KnownProfile
from pkgcore.ebuild.repository import UnconfiguredTree

from nattka.bugzilla import BugInfo, BugCategory, arches_from_cc
from nattka.keyword import update_keywords_in_file, keyword_sort_key


class RepoTuple(typing.NamedTuple):
    domain: pkgcore.ebuild.domain.domain
    repo: UnconfiguredTree


class PackageKeywords(typing.NamedTuple):
    package: pkgcore.ebuild.ebuild_src.package
    keywords: typing.List[str]


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


class PackageMatchException(Exception):
    pass


class PackageNoMatch(PackageMatchException):
    pass


class KeywordNoMatch(PackageMatchException):
    pass


class PackageInvalid(PackageMatchException):
    pass


class KeywordNotSpecified(PackageMatchException):
    def __init__(self,
                 pkgs: typing.List[str],
                 message: str):
        self.pkgs = pkgs
        return super().__init__(message)


class KeywordNoneLeft(Exception):
    pass


class PackageListEmpty(PackageMatchException):
    pass


class PackageListDoneAlready(PackageListEmpty):
    pass


class ExpandImpossible(Exception):
    pass


COMMENT_RE = re.compile(r'(^|\s)#.*$')
WS_RE = re.compile(r'(\s+)')


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


def select_best_version(matches: typing.Iterable[
                        pkgcore.ebuild.ebuild_src.package]
                        ) -> pkgcore.ebuild.ebuild_src.package:
    """
    Select the most suitable package version from `matches`

    The newest version having any keywords is preferred.  If no versions
    have keywords, the newest not having PROPERTIES=live will be
    selected.  If all versions are live, the newest one will be taken.
    """

    s_matches = sorted(matches)
    for m in reversed(s_matches):
        if m.keywords:
            return m
    for m in reversed(s_matches):
        if 'live' not in m.properties:
            return m
    for m in reversed(s_matches):
        return m


def filter_prefix_keywords(kw: typing.Iterable[str]
                           ) -> typing.List[str]:
    """Filter prefix keywords out of `kw`, returning a new list"""
    # TODO: technically this would match *-fbsd if we still had it
    return [x for x in kw if '-' not in x]


def get_suggested_keywords(repo: UnconfiguredTree,
                           pkg: pkgcore.ebuild.ebuild_src.package,
                           streq: bool
                           ) -> typing.FrozenSet[str]:
    """
    Get suggested (`*`) keywords for a given package

    `repo` is the repository instance, `pkg` is the matched package,
    `streq` specifies whether we're dealing with a stablereq (True)
    or keywordreq (False).
    """

    # get keywords from other versions
    keyword_iter = itertools.chain.from_iterable(
        x.keywords for x in repo.match(pkg.unversioned_atom))
    disallow_prefix = ('-~' if streq else '-')
    match_keywords = set(
        x.lstrip('~') for x in keyword_iter
        if x[0] not in disallow_prefix)

    if streq:
        # limit stablereq to whatever is ~arch right now
        match_keywords.intersection_update(
            x.lstrip('~') for x in pkg.keywords
            if x[0] == '~')
    else:
        # limit keywordreq to missing keywords and not -*
        # (i.e. strip all keywords already present)
        match_keywords.difference_update(
            x.lstrip('~-') for x in pkg.keywords)

    return frozenset(filter_prefix_keywords(match_keywords))


def match_package_list(repo: UnconfiguredTree,
                       bug: BugInfo,
                       only_new: bool = False,
                       filter_arch: typing.Iterable[str] = [],
                       permit_allarches: bool = False
                       ) -> typing.Iterator[PackageKeywords]:
    """
    Match `bug` against packages in `repo`

    Return an iterator over pair of PackageKeywords.  If any of
    the items fail to match, raise an exception.

    If no keywords are provided for a package, they are inferred
    from CC list (if present).  Otherwise, the specified keywords
    are filtered to intersection with CC list.

    If `only_new` is True, keywords already present on the package
    will be skipped, and only new keywords will be returned.

    If `filter_arch` is non-empty, only arches present in the list
    will be returned.

    If `permit_allarches` is True, all potential keywords will be
    returned in packages requested for ALLARCHES stabilization,
    even if they would normally be filtered out via `filter_arch`.
    """

    valid_arches = frozenset(repo.known_arches)
    cc_arches = arches_from_cc(bug.cc, valid_arches)
    filter_arch = frozenset(filter_arch)

    keyworded_already = False
    filtered = False
    yielded = False
    no_potential_keywords = []
    no_keywords = []

    prev_keywords = None
    for line in bug.atoms.splitlines():
        sl = COMMENT_RE.sub('', line).split()
        if not sl:
            continue

        dep = None
        for prefix in ('=', ''):
            sdep = prefix + sl[0]
            try:
                dep = atom(sdep, eapi='5')
                break
            except MalformedAtom:
                pass

        streq = bug.category == BugCategory.STABLEREQ

        if dep is None or dep.blocks or dep.use or dep.slot_operator:
            raise PackageInvalid(
                f'invalid package spec: {sdep}')
        if streq and (dep.op != '=' or dep.slot):
            raise PackageInvalid(
                f'disallowed package spec (only = allowed): {dep}')

        m = repo.match(dep)
        if not m:
            raise PackageNoMatch(
                f'no match for package: {sl[0]}')

        if not streq:
            pkg = select_best_version(m)
        else:
            assert len(m) == 1
            pkg = m[0]

        keywords = [x.strip().lstrip('~') for x in sl[1:]]
        if '-' in keywords:
            continue
        if '*' in keywords:
            match_keywords = get_suggested_keywords(repo, pkg, streq)
            keywords = (
                sorted(match_keywords, key=keyword_sort_key)
                + [x for x in keywords if x != '*'])
        if '^' in keywords:
            if prev_keywords is None:
                raise KeywordNoMatch(
                    'invalid use of ^ keyword on first line')
            keywords = prev_keywords + [x for x in keywords if x != '^']

        unknown_keywords = frozenset(keywords) - valid_arches
        if unknown_keywords:
            raise KeywordNoMatch(
                f'incorrect keywords: {" ".join(unknown_keywords)}')

        if not keywords:
            keywords = cc_arches
        elif cc_arches:
            # filter through CC list
            keywords = [x for x in keywords if x in cc_arches]
            # skip packages that are no longer relevant to CC
            if not keywords:
                continue

        if not keywords:
            if not get_suggested_keywords(repo, pkg, streq):
                no_potential_keywords.append(sdep)
            else:
                no_keywords.append(sdep)
            yield PackageKeywords(pkg, keywords)
            continue
        prev_keywords = keywords

        # we still do filtering with ALLARCHES since the requested
        # arches may be disjoint with ALLARCHES candidates
        allarches_kw: typing.FrozenSet[str] = frozenset()
        if (permit_allarches and bug.category == BugCategory.STABLEREQ
                and 'ALLARCHES' in bug.keywords):
            # this is called only in 'apply' command
            assert filter_arch
            # ALLARCHES keywords are the same as `*`
            allarches_kw = get_suggested_keywords(repo, pkg, True)

        if only_new:
            keywords = [k for k in keywords
                        if k not in pkg.keywords
                        and (streq or f'~{k}' not in pkg.keywords)]
            # skip packages that are done already
            if not keywords:
                keyworded_already = True
                continue

        if filter_arch:
            keywords = [k for k in keywords if k in filter_arch]
            for k in allarches_kw:
                if k not in keywords:
                    keywords.append(k)
            # skip packages that are filtered away entirely
            if not keywords:
                filtered = True
                continue

        yield PackageKeywords(pkg, keywords)
        yielded = True

    if no_keywords:
        raise KeywordNotSpecified(no_keywords,
                                  f'incomplete keywords for packages: '
                                  f'{" ".join(no_keywords)})')
    elif no_potential_keywords:
        # report KeywordNoneLeft only if no other entries were reported
        # otherwise, the bug is still considered interesting
        if not yielded:
            raise KeywordNoneLeft('package keywords in line with other '
                                  'versions and none specified')
        else:
            raise KeywordNotSpecified(no_potential_keywords,
                                      f'incomplete keywords for packages: '
                                      f'{" ".join(no_potential_keywords)}')
    if not yielded:
        if filtered:
            raise PackageListEmpty('no packages match requested arch')
        elif keyworded_already:
            raise PackageListDoneAlready('all packages keyworded already')
        else:
            raise PackageListEmpty('empty package list')


def expand_package_list(repo: UnconfiguredTree,
                        bug: BugInfo,
                        target_cc: typing.Iterable[str],
                        ) -> str:
    """
    Expand `*` and `^` entries in package list

    `repo` is the repository, `bug` is the original bug to work on.
    `target_cc` specifies expected CC list (to simplify "*").  Returns
    new package list contents.

    Note that this function assumes that match_package_list() has been
    called already, and did not raise any exceptions, i.e. that the bug
    is known to have a valid package list.
    """

    target_cc = frozenset(target_cc)
    ret = ''
    prev_kw = None
    for line in bug.atoms.splitlines(keepends=True):
        it = iter(WS_RE.split(line))
        pkg = None
        cur_kw: typing.Optional[typing.List[str]] = None
        had_empty_above = False
        for w in it:
            if w.startswith('#'):
                ret += w
                break
            if w.strip() and pkg is None:
                dep = None
                for prefix in ('=', ''):
                    sdep = prefix + w
                    try:
                        dep = atom(sdep, eapi='5')
                        break
                    except MalformedAtom:
                        pass
                assert dep

                m = repo.match(dep)
                assert m
                pkg = select_best_version(m)
                cur_kw = []
            elif w == '*':
                assert target_cc
                match_keywords = get_suggested_keywords(
                    repo, pkg, bug.category == BugCategory.STABLEREQ)
                if target_cc == set(f'{x}@gentoo.org'
                                    for x in match_keywords):
                    w = ''
                elif match_keywords:
                    w = ' '.join(
                        sorted(match_keywords, key=keyword_sort_key))
                else:
                    w = '-'
            elif w == '^':
                assert prev_kw is not None
                if not prev_kw:
                    if len(cur_kw) > 1:
                        raise ExpandImpossible(
                            'keywords along with empty ^')
                    had_empty_above = True
                # [0] is pkg string
                w = ' '.join(prev_kw)
            # collect keywords for next ^ occurence
            if pkg is not None:
                assert cur_kw is not None
                if w.strip():
                    if had_empty_above:
                        raise ExpandImpossible(
                            'keywords along with empty ^')
                    cur_kw.append(w)
            ret += w
        if cur_kw is not None:
            prev_kw = cur_kw[1:]

        # copy remaining part
        ret += ''.join(it)

    return ret


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
                       ) -> CheckResult:
    """
    Check whether dependencies are satisfied for package-arch @tuples,
    in @repo.  Returns a pair of (boolean status, error list).
    """

    errors = []
    ret = True

    for keywords, packages in itertools.groupby(tuples, lambda x: x[1]):
        package_strs = list((str(x[0].versioned_atom) for x in packages))
        results = pkgcheck.scan(['-c', 'VisibilityCheck',
                                 '-p', 'stable,dev',
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

    return dict((k.cpvstr, sorted(v, key=keyword_sort_key))
                for k, v in tuples)


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


def is_allarches(pkg: pkgcore.ebuild.ebuild_src.package
                 ) -> bool:
    """
    Verify whether `pkg` is marked for ALLARCHES stabilization

    Return True if it is, False otherwise (including when metadata.xml
    is missing).  Raise exception if metadata.xml is malformed.
    """

    try:
        # we open it ourselves because error handling in lxml sucks
        # (doesn't return errno / distinguish failure reason)
        with open(Path(pkg.path).parent / 'metadata.xml', 'r') as f:
            xml = lxml.etree.parse(f)
    except FileNotFoundError:
        return False

    for allarches in xml.findall('stabilize-allarches'):
        r = allarches.get('restrict')
        try:
            if r is None:
                return True
            dep = atom(r, eapi='0')
            if dep.key != pkg.key:
                raise PackageInvalid(f'restrict refers to wrong package: {r} '
                                     f'(in {pkg.cpvstr})')
            if dep.match(pkg):
                return True
        except MalformedAtom:
            raise PackageInvalid(f'invalid restrict: {r} (in {pkg.cpvstr})')
    return False


def can_allarches_for_keywords(repo: UnconfiguredTree,
                               tuples: PackageKeywordsIterable,
                               ) -> bool:
    """
    Verify whether `pkg` is actually suitable for ALLARCHES.

    Return True if all packages in tuples have at least one stable
    version on each requested architecture, False otherwise.
    """

    for req_package, keywords in tuples:
        keywords_left = set(keywords)
        for p in repo.itermatch(req_package.unversioned_atom):
            # NB: we don't need to filter ~arch or -arch keywords, they
            # just won't match anything
            keywords_left.difference_update(p.keywords)
        # if we couldn't match at least one keyword, we can't
        # do ALLARCHES
        if keywords_left:
            return False
    return True


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
