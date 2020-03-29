""" Package processing support. """

import io
import itertools
import subprocess
import typing

# need to preload it to fix pkgcheck.reporters import error
__import__('pkgcheck.checks')
from pkgcheck.reporters import PickleStream
import pkgcore.ebuild.ebuild_src

from gentoolkit.ekeyword import ekeyword
from pkgcore.config import load_config
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcore.util import parserestrict


class PackageKeywords(typing.NamedTuple):
    package: pkgcore.ebuild.ebuild_src.package
    keywords: typing.List[str]


class CheckResult(typing.NamedTuple):
    success: bool
    output: typing.List[dict]


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

    for l in package_list.splitlines():
        sl = l.split()
        if not sl:
            continue
        keywords = [x.strip().lstrip('~') for x in sl[1:]]
        for m in repo.itermatch(parserestrict.parse_match('=' + sl[0].strip())):
            yield PackageKeywords(m, keywords)


def add_keywords(tuples: typing.Iterator[PackageKeywords], stable: bool
        ) -> None:
    """
    Add testing (stable=False) or stable (stable=True) keywords to
    ebuilds, as specified by package-keyword tuples.
    """

    for p, keywords in tuples:
        ebuild = p.path
        ops = [ekeyword.Op(None if stable else '~', k, None) for k in keywords]
        ekeyword.process_ebuild(ebuild, ops, quiet=2)


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
