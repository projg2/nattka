""" Package processing support. """

from gentoolkit.ekeyword import ekeyword
from pkgcore.util import parserestrict


def match_package_list(repo, package_list):
    """
    Match @package_list against packages in @repo.  Returns an iterator
    over pairs of (package object, keywords).  If any of the items fails
    to match, raises an exception.
    """

    for l in package_list.splitlines():
        sl = l.split()
        if not sl:
            continue
        keywords = [x.strip().lstrip('~') for x in sl[1:]]
        for m in repo.itermatch(parserestrict.parse_match('=' + sl[0].strip())):
            yield m, keywords


def add_keywords(tuples, stable):
    """
    Add testing (stable=False) or stable (stable=True) keywords to
    ebuilds, as specified by package-keyword tuples.
    """

    for p, keywords in tuples:
        ebuild = p.path
        ops = [ekeyword.Op(None if stable else '~', k, None) for k in keywords]
        ekeyword.process_ebuild(ebuild, ops, quiet=2)
