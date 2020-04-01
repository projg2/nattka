# (c) 2020 Michał Górny
# 2-clause BSD license

""" Package processing support. """

import io
import itertools
import subprocess
import typing

# need to preload it to fix pkgcheck.reporters import error
__import__('pkgcheck.checks')
from pkgcheck.reporters import PickleStream
import pkgcore.ebuild.ebuild_src

from pkgcore.config import load_config
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.errors import MalformedAtom
from pkgcore.ebuild.repository import UnconfiguredTree

from nattka.keyword import update_keywords_in_file


class PackageKeywords(typing.NamedTuple):
    package: pkgcore.ebuild.ebuild_src.package
    keywords: typing.List[str]


class CheckResult(typing.NamedTuple):
    success: bool
    output: typing.List[dict]


class PackageNoMatch(Exception):
    pass


class KeywordNoMatch(Exception):
    pass


class PackageInvalid(Exception):
    pass


def find_repository(path: str, conf_path: str = None
        ) -> UnconfiguredTree:
    """
    Find an ebuild repository in specified @path, and return initiated
    repo object for it.  If @conf_path is specified, it overrides
    config location.
    """
    c = load_config(location=conf_path)
    domain = c.get_default('domain')
    return domain.find_repo(path, config=c, configure=False)


def match_package_list(repo: UnconfiguredTree, package_list: str
        ) -> typing.Iterator[PackageKeywords]:
    """
    Match @package_list against packages in @repo.  Returns an iterator
    over pairs of PackageKeywords.  If any of the items fails to match,
    raises an exception.
    """

    valid_arches = frozenset(repo.known_arches)
    for l in package_list.splitlines():
        sl = l.split()
        if not sl:
            continue
        keywords = [x.strip().lstrip('~') for x in sl[1:]]
        unknown_keywords = frozenset(keywords) - valid_arches
        if unknown_keywords:
            raise KeywordNoMatch(
                f'incorrect keywords: {" ".join(unknown_keywords)}')

        dep = None
        for sdep in (f'={sl[0].strip()}', sl[0].strip()):
            try:
                dep = atom(sdep, eapi='0')
                break
            except MalformedAtom:
                pass

        if dep is None or dep.blocks:
            raise PackageInvalid(
                f'invalid package spec: {sdep}')
        if dep.op != '=':
            raise PackageInvalid(
                f'disallowed package spec (only = allowed): {dep}')

        m = repo.match(dep)
        if not m:
            raise PackageNoMatch(
                f'no match for package: {sl[0]}')
        assert len(m) == 1
        yield PackageKeywords(m[0], keywords)


def add_keywords(tuples: typing.Iterator[PackageKeywords], stable: bool
        ) -> None:
    """
    Add testing (stable=False) or stable (stable=True) keywords to
    ebuilds, as specified by package-keyword tuples.
    """

    for p, keywords in tuples:
        update_keywords_in_file(p.path, keywords, stable=stable)


def check_dependencies(repo: UnconfiguredTree, tuples: typing.Iterable[
        PackageKeywords]) -> CheckResult:
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
