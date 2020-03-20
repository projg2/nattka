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


BugInfo = collections.namedtuple('BugInfo',
    ('category', 'atoms', 'arches_cc', 'depends', 'blocks'))


class NattkaBugzilla(object):
    def __init__(self, api_key, url=BUGZILLA_URL):
        self.bz = bugzilla.Bugzilla(url, api_key=api_key)

    def fetch_package_list(self, bugs):
        """
        Fetch specified @bugs (list of bug numberss).  Returns
        an iterator over BugInfo tuples.
        """

        for b in self.bz.getbugs(bugs, include_fields=list(INCLUDE_BUG_FIELDS)):
            bcat = BugCategory.from_component(b.component)
            atoms = b.cf_stabilisation_atoms + '\r\n'
            cced = set()
            for e in b.cc:
                if e in KNOWN_ARCHES:
                    cced.add(e.split('@')[0])
            yield BugInfo(bcat, atoms, cced, b.depends_on, b.blocks)
