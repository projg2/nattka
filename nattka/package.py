""" Package processing support. """

import collections
import itertools
import json
import subprocess

from gentoolkit.ekeyword import ekeyword
from pkgcore.config import load_config
from pkgcore.util import parserestrict


PackageKeywords = collections.namedtuple('PackageKeyword',
    ('package', 'keywords'))

CheckResult = collections.namedtuple('CheckResult',
    ('success', 'output'))


def find_repository(path, conf_path=None):
    """
    Find an ebuild repository in specified @path, and return initiated
    repo object for it.  If @conf_path is specified, it overrides
    config location.
    """
    c = load_config(location=conf_path)
    domain = c.get_default('domain')
    return domain.find_repo(path, config=c, configure=False)


def match_package_list(repo, package_list):
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


def add_keywords(tuples, stable):
    """
    Add testing (stable=False) or stable (stable=True) keywords to
    ebuilds, as specified by package-keyword tuples.
    """

    for p, keywords in tuples:
        ebuild = p.path
        ops = [ekeyword.Op(None if stable else '~', k, None) for k in keywords]
        ekeyword.process_ebuild(ebuild, ops, quiet=2)


def check_dependencies(repo, tuples):
    """
    Check whether dependencies are satisfied for package-arch @tuples,
    in @repo.  Returns a pair of (boolean status, error list).
    """

    errors = []
    ret = True

    for keywords, packages in itertools.groupby(tuples, lambda x: x[1]):
        packages = list((str(x[0].versioned_atom) for x in packages))
        args = ['pkgcheck', 'scan', '-c', 'VisibilityCheck',
                '-R', 'JsonStream', '-a', ','.join(keywords)] + packages
        sp = subprocess.Popen(args,
                              cwd=repo.location,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        sout, serr = sp.communicate()
        for l in sout.splitlines():
            j = json.loads(l)
            if j['__class__'].startswith('NonsolvableDeps'):
                ret = False
                errors.append(j)

    return CheckResult(ret, errors)


def fill_keywords(repo, tuples, cc):
    """
    Fill missing keywords in @tuples based on @cc list.  @repo is used
    to determine valid arches.  Returns an iterator over updated tuples.
    """

    arches = frozenset(f'{x}@gentoo.org' for x in repo.known_arches)
    for p, keywords in tuples:
        if not keywords:
            keywords = [x.split('@')[0] for x in arches.intersection(cc)]
        yield p, keywords
