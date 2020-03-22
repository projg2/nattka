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
    ('category', 'atoms', 'cc', 'depends', 'blocks'))


def make_bug_info(bug):
    bcat = BugCategory.from_component(bug.component)
    atoms = bug.cf_stabilisation_atoms + '\r\n'
    return BugInfo(bcat, atoms, bug.cc, bug.depends_on, bug.blocks)


class NattkaBugzilla(object):
    def __init__(self, api_key, url=BUGZILLA_URL):
        self.bz = bugzilla.Bugzilla(url, api_key=api_key)

    def fetch_package_list(self, bugs):
        """
        Fetch specified @bugs (list of bug numbers).  Returns a dict
        of {bugno: buginfo}.
        """

        ret = {}
        for b in self.bz.getbugs(bugs, include_fields=list(INCLUDE_BUG_FIELDS)):
            ret[b.id] = make_bug_info(b)
        return ret


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
