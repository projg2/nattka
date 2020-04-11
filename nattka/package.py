# (c) 2020 Michał Górny
# 2-clause BSD license

""" Package processing support. """

import io
import itertools
import subprocess
import typing

from pathlib import Path

# need to preload it to fix pkgcheck.reporters import error
__import__('pkgcheck.checks')
from pkgcheck.reporters import PickleStream
from pkgcheck.results import Result

import pkgcore.ebuild.domain
import pkgcore.ebuild.ebuild_src
from pkgcore.config import load_config
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.errors import MalformedAtom
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


class CheckResult(typing.NamedTuple):
    success: bool
    output: typing.List[Result]


class PackageNoMatch(Exception):
    pass


class KeywordNoMatch(Exception):
    pass


class PackageInvalid(Exception):
    pass


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
        try:
            path.relative_to(repo.location)
        except ValueError:
            pass
        else:
            return RepoTuple(domain, repo)

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


def match_package_list(repo: UnconfiguredTree,
                       bugs: typing.Iterable[BugInfo]
                       ) -> typing.Iterator[PackageKeywords]:
    """
    Match `bugs` against packages in `repo`

    Return an iterator over pair of PackageKeywords.  If any of
    the items fail to match, raise an exception.

    If no keywords are provided for a package, they are inferred
    from CC list (if present).  Otherwise, the specified keywords
    are filtered to intersection with CC list.
    """

    valid_arches = frozenset(repo.known_arches)
    for bug in bugs:
        cc_arches = arches_from_cc(bug.cc, valid_arches)
        prev_keywords = None
        for l in bug.atoms.splitlines():
            sl = l.split()
            if not sl:
                continue

            dep = None
            for sdep in (f'={sl[0].strip()}', sl[0].strip()):
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
            if '*' in keywords:
                # get keywords from other versions
                keyword_iter = itertools.chain.from_iterable(
                    x.keywords for x in repo.match(dep.unversioned_atom))
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

            yield PackageKeywords(pkg, keywords)
            prev_keywords = keywords


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
        args = ['pkgcheck', 'scan', '-c', 'VisibilityCheck',
                '-R', 'PickleStream', '-a', ','.join(keywords)] + package_strs
        sp = subprocess.Popen(args,
                              cwd=repo.location,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        sout, serr = sp.communicate()

        for r in PickleStream.from_file(io.BytesIO(sout)):
            if r.name.startswith('NonsolvableDeps'):
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
