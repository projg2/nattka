""" Bugzilla support. """

import collections
import enum

import requests


BUGZILLA_API_URL = 'https://bugs.gentoo.org/rest'

INCLUDE_BUG_FIELDS = (
    'id',
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
            return ['Keywording']
        elif val == cls.STABLEREQ:
            return ['Stabilization', 'Vulnerabilities']
        else:
            return ['Keywording', 'Stabilization', 'Vulnerabilities']


BugInfo = collections.namedtuple('BugInfo',
    ('category', 'atoms', 'cc', 'depends', 'blocks'))


def make_bug_info(bug):
    bcat = BugCategory.from_component(bug['component'])
    atoms = bug['cf_stabilisation_atoms'] + '\r\n'
    return BugInfo(bcat, atoms, bug['cc'], bug['depends_on'], bug['blocks'])


class NattkaBugzilla(object):
    def __init__(self, api_key, api_url=BUGZILLA_API_URL):
        self.api_key = api_key
        self.api_url = api_url
        self.session = requests.Session()

    def _request(self, endpoint, params):
        params = dict(params)
        params['Bugzilla_api_key'] = self.api_key
        params['include_fields'] = INCLUDE_BUG_FIELDS
        ret = self.session.get(self.api_url + '/' + endpoint,
                               params=params)
        ret.raise_for_status()
        return ret

    def fetch_package_list(self, bugs):
        """
        Fetch specified @bugs (list of bug numbers).  Returns a dict
        of {bugno: buginfo}.
        """

        resp = self._request('bug',
                             params={
                                 'id': ','.join(str(x) for x in bugs)
                             }).json()

        ret = {}
        for b in resp['bugs']:
            ret[b['id']] = make_bug_info(b)
        return ret

    def find_bugs(self, category, limit=None):
        """
        Find all relevant bugs in @category.  Limit to @limit results
        (None = no limit).
        """

        search_params = {
            'resolution': '---',
        }
        component = BugCategory.to_components(category)
        if component is not None:
            search_params['component'] = component
        if limit is not None:
            search_params['limit'] = limit

        resp = self._request('bug', params=search_params).json()

        ret = {}
        for b in resp['bugs']:
            # skip empty bugs (likely security issues that are not
            # stabilization requests)
            if not b['cf_stabilisation_atoms'].strip():
                continue
            ret[b['id']] = make_bug_info(b)
        return ret
