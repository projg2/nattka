""" Bugzilla support. """

import collections
import enum

import bugzilla


BUGZILLA_URL = 'https://bugs.gentoo.org'

INCLUDE_BUG_FIELDS = (
    'component',
    'cf_stabilisation_atoms',
    'cc',
    'depends_on',
    'blocks',
)

# TODO: get it from repo?
KNOWN_ARCHES = (
    'alpha@gentoo.org',
    'amd64@gentoo.org',
    'arm64@gentoo.org',
    'arm@gentoo.org',
    'hppa@gentoo.org',
    'ia64@gentoo.org',
    'm68k@gentoo.org',
    'mips@gentoo.org',
    'ppc64@gentoo.org',
    'ppc@gentoo.org',
    'riscv@gentoo.org',
    's390@gentoo.org',
    'sh@gentoo.org',
    'sparc@gentoo.org',
    'x86@gentoo.org',
)


class BugCategory(enum.Enum):
    KEYWORDREQ = enum.auto()
    STABLEREQ = enum.auto()

    @classmethod
    def from_component(cls, component):
        if component in ('Keywording',):
            return cls.KEYWORDREQ
        elif component in ('Stabilization', 'Vulnerabilities'):
            return cls.STABLEREQ
        else:
            return None

    @classmethod
    def to_components(cls, val):
        if val == cls.KEYWORDREQ:
            return ['keywording']
        elif val == cls.STABLEREQ:
            return ['Stabilization', 'Vulnerabilities']
        else:
            return None


BugInfo = collections.namedtuple('BugInfo',
    ('category', 'atoms', 'arches_cc', 'depends', 'blocks'))


def make_bug_info(bug):
    bcat = BugCategory.from_component(bug.component)
    atoms = bug.cf_stabilisation_atoms + '\r\n'
    cced = set()
    for e in bug.cc:
        if e in KNOWN_ARCHES:
            cced.add(e.split('@')[0])
    return BugInfo(bcat, atoms, cced, bug.depends_on, bug.blocks)


class NattkaBugzilla(object):
    def __init__(self, api_key, url=BUGZILLA_URL):
        self.bz = bugzilla.Bugzilla(url, api_key=api_key)

    def fetch_package_list(self, bugs):
        """
        Fetch specified @bugs (list of bug numberss).  Returns
        an iterator over BugInfo tuples.
        """

        for b in self.bz.getbugs(bugs, include_fields=list(INCLUDE_BUG_FIELDS)):
            yield make_bug_info(b)


    def find_bugs(self, category, limit=None):
        """
        Find all relevant bugs in @category.  Limit to @limit results
        (None = no limit).
        """

        query = self.bz.build_query(
            component=BugCategory.to_components(category),
            status=['UNCONFIRMED', 'CONFIRMED', 'IN_PROGRESS'],
            include_fields=list(INCLUDE_BUG_FIELDS))
        # TODO: a hack
        if limit is not None:
            query['limit'] = limit

        ret = {}
        for b in self.bz.query(query):
            # skip empty bugs (likely security issues that are not
            # stabilization requests)
            if not b.cf_stabilisation_atoms:
                continue
            ret[b.id] = make_bug_info(b)
        return ret
