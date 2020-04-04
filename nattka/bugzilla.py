# (c) 2020 Michał Górny
# 2-clause BSD license

""" Bugzilla support. """

import enum
import typing

import requests


BUGZILLA_API_URL = 'https://bugs.gentoo.org/rest'

INCLUDE_BUG_FIELDS = [
    'id',
    'product',
    'component',
    'cf_stabilisation_atoms',
    'cc',
    'depends_on',
    'blocks',
    'flags',
]


class BugCategory(enum.Enum):
    KEYWORDREQ = enum.auto()
    STABLEREQ = enum.auto()

    @classmethod
    def from_product_component(cls,
                               product: str,
                               component: str
                               ) -> typing.Optional['BugCategory']:
        """
        Return a BugCategory for bug in @product and @component.
        """

        if product == 'Gentoo Linux':
            if component == 'Keywording':
                return cls.KEYWORDREQ
            elif component == 'Stabilization':
                return cls.STABLEREQ
        elif product == 'Gentoo Security':
            if component in ('Vulnerabilities', 'Kernel'):
                return cls.STABLEREQ
        return None

    @classmethod
    def to_products_components(cls,
                               val: typing.Optional['BugCategory']
                               ) -> typing.Tuple[typing.List[str],
                                                 typing.List[str]]:
        """
        Return a tuple of valid bug products and components for a given
        category.
        """

        if val == cls.KEYWORDREQ:
            return (['Gentoo Linux'], ['Keywording'])
        elif val == cls.STABLEREQ:
            return (['Gentoo Linux', 'Gentoo Security'],
                    ['Stabilization', 'Vulnerabilities', 'Kernel'])
        else:
            return (['Gentoo Linux', 'Gentoo Security'],
                    ['Keywording', 'Stabilization', 'Vulnerabilities',
                     'Kernel'])


class BugInfo(typing.NamedTuple):
    category: typing.Optional[BugCategory]
    atoms: str
    cc: typing.List[str]
    depends: typing.List[int]
    blocks: typing.List[int]
    sanity_check: typing.Optional[bool]


def make_bug_info(bug: typing.Dict[str, typing.Any]
                  ) -> BugInfo:
    bcat = BugCategory.from_product_component(bug['product'],
                                              bug['component'])
    atoms = bug['cf_stabilisation_atoms'] + '\r\n'
    sanity_check = None
    for f in bug['flags']:
        if f['name'] == 'sanity-check':
            if f['status'] == '+':
                sanity_check = True
            elif f['status'] == '-':
                sanity_check = False

    return BugInfo(bcat, atoms, bug['cc'], bug['depends_on'],
                   bug['blocks'], sanity_check)


class NattkaBugzilla(object):
    def __init__(self,
                 api_key: typing.Optional[str],
                 api_url: typing.Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url or BUGZILLA_API_URL
        self.session = requests.Session()

    def _request(self,
                 endpoint: str,
                 params: typing.Mapping[str, typing.Union[
                     typing.Iterable[str], str
                 ]] = {}
                 ) -> requests.Response:
        params = dict(params)
        if self.api_key is not None:
            params['Bugzilla_api_key'] = self.api_key
        ret = self.session.get(self.api_url + '/' + endpoint,
                               params=params)
        ret.raise_for_status()
        return ret

    def _request_put(self,
                     endpoint: str,
                     data: dict
                     ) -> requests.Response:
        data = dict(data)
        params = {}
        if self.api_key is not None:
            params['Bugzilla_api_key'] = self.api_key
        ret = self.session.put(self.api_url + '/' + endpoint,
                               json=data,
                               params=params)
        ret.raise_for_status()
        return ret

    def whoami(self) -> str:
        """
        Return username for the current Bugzilla user.
        """
        return self._request('whoami').json()['name']

    def find_bugs(self,
                  bugs: typing.Iterable[int] = [],
                  category: typing.Iterable[BugCategory] = [],
                  cc: typing.Iterable[BugCategory] = []
                  ) -> typing.Dict[int, BugInfo]:
        """
        Fetch and return all bugs relevant to the query.

        If `bugs` list is not empty, bugs listed in it are fetched.
        If it is empty, the function searches for all open keywording
        and stabilization bugs.  In both cases, results are further
        filtered by the conditions specified in other parameters.

        If `category` is not empty, it specifies the bug categories
        to include in the results.  Otherwise, all bugs are included
        (including bugs not belonging to any category, if `bugs`
        are specified as well).

        If `cc` is not empty, only bugs with specific e-mail addresses
        in CC will be returned.

        Return a dict mapping bug numbers to `BugInfo` instances.
        The keys include only successfully fetched bugs.  If `bugs`
        specifies bugs that do not exist or do not match the criteria,
        they will not be included in the result.
        """

        search_params = {
            'include_fields': INCLUDE_BUG_FIELDS,
        }
        if bugs:
            search_params['id'] = list(str(x) for x in bugs)
        else:
            # if no bugs specified, limit to open keywordreqs & stablereqs
            search_params['resolution'] = ['---']
            if not category:
                category = [BugCategory.KEYWORDREQ, BugCategory.STABLEREQ]

        if category:
            products = set()
            components = set()
            for cat in category:
                prod, comp = BugCategory.to_products_components(cat)
                products.update(prod)
                components.update(comp)
            search_params['product'] = list(products)
            search_params['component'] = list(components)

        if cc:
            search_params['cc'] = list(cc)

        resp = self._request('bug', params=search_params).json()

        ret = {}
        for b in resp['bugs']:
            # skip empty bugs (likely security issues that are not
            # stabilization requests)
            # TODO: move this later in the pipeline
            if not bugs and not b['cf_stabilisation_atoms'].strip():
                continue
            ret[b['id']] = make_bug_info(b)
        return ret

    def get_latest_comment(self,
                           bugno: int,
                           username: str
                           ) -> typing.Optional[str]:
        """
        Get the latest comment left by @username on bug @bugno.
        Returns comment's text or None, if no matching comments found.
        """

        resp = self._request(f'bug/{bugno}/comment').json()
        for c in reversed(resp['bugs'][str(bugno)]['comments']):
            if c['creator'] == username:
                return c['text']
        return None

    def update_status(self,
                      bugno: int,
                      status: typing.Optional[bool],
                      comment: typing.Optional[str] = None
                      ) -> None:
        """
        Update the sanity-check status of bug @bugno.  @status specifies
        the new status (True, False or None to remove the flag),
        @comment is an optional comment to add.
        """

        if status is True:
            new_status = '+'
        elif status is False:
            new_status = '-'
        elif status is None:
            new_status = 'X'
        else:
            raise ValueError(f'Invalid status={status}')

        req = {
            'ids': [bugno],
            'flags': [
                {
                    'name': 'sanity-check',
                    'status': new_status,
                },
            ],
        }

        if comment is not None:
            req['comment'] = {
                'body': comment,
            }

        resp = self._request_put(f'bug/{bugno}', data=req).json()
        assert resp['bugs'][0]['id'] == bugno


def get_combined_buginfo(bugdict: typing.Dict[int, BugInfo],
                         bugno: int
                         ) -> BugInfo:
    """
    Combine information from linked (via 'depends on') bugs into
    a single BugInfo.  @bugdict is the dict returned by Bugzilla search,
    @bugno is the number of bug of interest.
    """

    topbug = bugdict[bugno]
    combined_bugs = [topbug]
    atoms = ''
    deps = set()

    i = 0
    while i < len(combined_bugs):
        atoms += combined_bugs[i].atoms
        for b in combined_bugs[i].depends:
            if b in bugdict and bugdict[b].category == topbug.category:
                combined_bugs.append(bugdict[b])
            else:
                deps.add(b)
        i += 1

    return BugInfo(topbug.category, atoms, topbug.cc, sorted(deps),
                   topbug.blocks, topbug.sanity_check)


def update_keywords_from_cc(bug: BugInfo,
                            known_arches: typing.Iterable[str]
                            ) -> BugInfo:
    """
    Update package package list's keywords in @bug based on CC.
    If at least one arch is CC-ed, the package's keywords are filtered
    to intersect with CC.  If package's keyword are not specified,
    they are defaulted to CC list.  Returns a BugInfo with updated
    package list.
    """

    # bug.cc may contain full emails when authorized with an API key
    # or just login names
    bug_cc = frozenset(x.split('@', 1)[0] for x in bug.cc
                       if x.endswith('@gentoo.org') or '@' not in x)
    arches = sorted(bug_cc.intersection(known_arches))

    # if no arches were CC-ed, we can't do anything
    if not arches:
        return bug

    ret = ''
    for line in bug.atoms.splitlines():
        sl = line.split()
        if len(sl) == 1:
            sl += arches
        else:
            sl[1:] = (x for x in sl[1:] if x.lstrip('~') in arches)
            # all arches filtered out? skip the package then
            if len(sl) == 1:
                continue
        ret += f'{" ".join(sl)}\r\n'

    return BugInfo(bug.category, ret, bug.cc, bug.depends, bug.blocks,
                   bug.sanity_check)
