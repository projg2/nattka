# (c) 2020 Michał Górny
# 2-clause BSD license

""" Bugzilla support. """

import enum
import typing

import requests

from nattka.keyword import keyword_sort_key


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
    'resolution',
    'keywords',
    'whiteboard',
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
                               val: 'BugCategory'
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
            assert False, f'Incorrect BugCategory: {val}'


class BugInfo(typing.NamedTuple):
    category: typing.Optional[BugCategory]
    security: bool
    atoms: str
    cc: typing.List[str]
    depends: typing.List[int]
    blocks: typing.List[int]
    sanity_check: typing.Optional[bool]
    resolved: bool
    keywords: typing.List[str]
    whiteboard: str


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

    return BugInfo(category=bcat,
                   security=(bug['product'] == 'Gentoo Security'),
                   atoms=atoms,
                   cc=bug['cc'],
                   depends=bug['depends_on'],
                   blocks=bug['blocks'],
                   sanity_check=sanity_check,
                   resolved=bool(bug['resolution']),
                   keywords=bug['keywords'],
                   whiteboard=bug['whiteboard'])


class NattkaBugzilla(object):
    def __init__(self,
                 api_key: typing.Optional[str],
                 api_url: typing.Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url or BUGZILLA_API_URL
        self.session = requests.Session()

    def _request(self,
                 endpoint: str,
                 params: typing.Mapping[str, typing.List[str]] = {},
                 put_data: typing.Optional[dict] = None
                 ) -> requests.Response:
        """
        Issue a request against Bugzilla REST API and return the response

        Issue a request against specified `endpoint`.  `params` are
        put in query string.  If `put_data` is None, a GET request
        is issued.  Otherwise, a PUT request is issued and `put_data`
        is passed as JSON request body.

        If the request is successfully issued, the JSON response body
        is returned.  Otherwise, an exception is raised.
        """

        params = dict(params)
        if self.api_key is not None:
            params['Bugzilla_api_key'] = [self.api_key]

        # NB: using .request() makes mypy unhappy
        if put_data is None:
            ret = self.session.get(self.api_url + '/' + endpoint,
                                   params=params,
                                   timeout=30)
        else:
            ret = self.session.put(self.api_url + '/' + endpoint,
                                   params=params,
                                   json=put_data,
                                   timeout=30)
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
                  unresolved: bool = False,
                  security: typing.Optional[bool] = None,
                  cc: typing.Iterable[str] = [],
                  sanity_check: typing.Iterable[bool] = [],
                  skip_tags: typing.Iterable[str] = []
                  ) -> typing.Dict[int, BugInfo]:
        """
        Fetch and return all bugs relevant to the query.

        If `bugs` list is not empty, only bugs listed in it are fetched.
        Otherwise, all bugs are searched.  In both cases, results are
        further refined by the conditions specified in other parameters.

        If `category` is not empty, it specifies the bug categories
        to include in the results.  Otherwise, all bugs are included
        (including bugs not belonging to any category, if `bugs`
        are specified as well).

        If `unresolved` is True, only open bugs are returned.

        If `security` is True, only security bugs are returned.  If it
        is False, only non-security bugs are returned.

        If `sanity-check` is not empty, only bugs matching specified
        sanity-check status will be returned.  The list can contain
        True for passing sanity check, or False for failing it.
        Finding bugs without sanity-check flag is not supported.

        If `cc` is not empty, only bugs with specific e-mail addresses
        in CC will be returned.

        If `skip_tags` is not empty, bugs containing specific user tags
        will be omitted.

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

        if category:
            products = set()
            components = set()
            for cat in category:
                prod, comp = BugCategory.to_products_components(cat)
                products.update(prod)
                components.update(comp)
            search_params['product'] = list(products)
            search_params['component'] = list(components)

        if unresolved:
            search_params['resolution'] = ['---']

        if security is not None:
            # note: this deliberately overrides category
            search_params['product'] = [
                'Gentoo Security' if security else 'Gentoo Linux']

        if cc:
            search_params['cc'] = list(cc)

        if sanity_check:
            search_params['f1'] = ['flagtypes.name']
            search_params['o1'] = ['anywords']
            search_params['v1'] = []
            for f in sanity_check:
                search_params['v1'].append(
                    'sanity-check' + ('+' if f else '-'))

        if skip_tags:
            search_params['f2'] = ['tag']
            search_params['o2'] = ['nowordssubstr']
            search_params['v2'] = list(skip_tags)

        resp = self._request('bug', params=search_params).json()

        return dict((b['id'], make_bug_info(b)) for b in resp['bugs'])

    def resolve_dependencies(self,
                             bugs: typing.Dict[int, BugInfo]
                             ) -> typing.Dict[int, BugInfo]:
        """
        Return `bugs` with missing dependencies filled in.

        Check dictionary `bugs` for missing dependencies, and fetch
        them recursively.  Return a dict with all dependencies present.
        """

        while True:
            missing: typing.Set[int] = set()
            for bug in bugs.values():
                missing.update(b for b in bug.depends if b not in bugs)
            # are all dependencies satisfied?
            if not missing:
                return bugs
            newbugs = self.find_bugs(missing)
            # verify that all bugs fetch, prevent dead loop
            assert all(x in newbugs for x in missing)
            # copy the dictionary to avoid modifying the original
            # (technically, this only needs to be done but no harm
            #  in repeating)
            bugs = dict(bugs)
            bugs.update(newbugs)

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
                      comment: typing.Optional[str] = None,
                      cc_add: typing.List[str] = [],
                      keywords_add: typing.List[str] = [],
                      keywords_remove: typing.List[str] = []
                      ) -> None:
        """
        Update the sanity-check status of bug

        `bugno` specifies the bug to update.  `status` is the new status
        (True for '+', False for '-', None to reset).  `comment`
        is an optional comment to add to the bug.  `cc_add` specifies
        CC entries (arches) to add, if not empty.  `keywords_add`
        and `keywords_remove` specified KEYWORDS to appropriately add
        or remove.
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
        if cc_add:
            req['cc'] = {
                'add': cc_add,
            }
        if keywords_add or keywords_remove:
            req['keywords'] = {
                'add': keywords_add,
                'remove': keywords_remove,
            }

        resp = self._request(f'bug/{bugno}', put_data=req).json()
        assert resp['bugs'][0]['id'] == bugno

    def resolve_bug(self,
                    bugno: int,
                    uncc: typing.Iterable[str],
                    comment: str,
                    resolve: bool = False
                    ) -> None:
        """
        Resolve the bug for given arches, and optionally close it

        Modify the bug `bugno` unCC-ing emails from `uncc` list, leaving
        a comment `comment` and closing the bug as FIXED if `resolve`
        is True.
        """

        req = {
            'ids': [bugno],
            'cc': {
                'remove': list(uncc),
            },
            'comment': {
                'body': comment,
            },
        }
        if resolve:
            req.update({
                'status': 'RESOLVED',
                'resolution': 'FIXED',
            })

        resp = self._request(f'bug/{bugno}', put_data=req).json()
        assert resp['bugs'][0]['id'] == bugno


def split_dependent_bugs(bugdict: typing.Dict[int, BugInfo],
                         bugno: int
                         ) -> typing.Tuple[typing.List[int], typing.List[int]]:
    """
    Split unresolved dependent bugs into keywording and regular bugs

    Traverse dependency tree of `bugno`, using data from `bugdict`.
    Return a tuple of two bug lists.  The first list contains bugs that
    are of the same category (keywording or stabilization bugs),
    the second list other bugs.  The requested bug itself is not
    included in the list.  Resolved bugs are skipped.  Bugs missing
    from `bugdict` are returned in the second list.
    """

    kw_bugs = [bugno]
    reg_bugs = set()
    i = 0
    while i < len(kw_bugs):
        curbug = bugdict[kw_bugs[i]]
        for b in curbug.depends:
            if b not in bugdict:
                # can't tell if it's a blocker or not, so stay
                # on the safe side
                reg_bugs.add(b)
            elif bugdict[b].resolved:
                pass
            elif bugdict[b].category == curbug.category:
                if b not in kw_bugs:
                    kw_bugs.append(b)
            else:
                reg_bugs.add(b)
        i += 1

    return sorted(kw_bugs[1:]), sorted(reg_bugs)


def arches_from_cc(cc: typing.Iterable[str],
                   known_arches: typing.Iterable[str]
                   ) -> typing.List[str]:
    """
    Return list of arches found in CC of a bug

    Return an intersection of CC list of a bug `cc`, and the list
    of valid arches `known_arches`.  The resulting list will contain
    pure arch names (not e-mail addresses), and be sorted in keyword
    order.
    """

    # bug.cc may contain full emails when authorized with an API key
    # or just login names
    cc_names = frozenset(x.split('@', 1)[0] for x in cc
                         if x.endswith('@gentoo.org') or '@' not in x)
    return sorted(cc_names.intersection(known_arches),
                  key=keyword_sort_key)
