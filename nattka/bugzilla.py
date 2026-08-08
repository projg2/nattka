# (c) 2020-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

""" Bugzilla support.

The client, the bug records and the query builder all come from
:mod:`pkgcore.bugzilla`.  What is left here is the policy pkgcore has no
business knowing: which bugs nattka acts on, how a dependency tree splits into
same-category bugs and real blockers, and the order arches are reported in.
"""

import typing

from pkgcore.bugzilla import Bug, Bugzilla
from pkgcore.bugzilla.client import DEFAULT_URL

from nattka import __version__

BUGZILLA_API_URL = f'{DEFAULT_URL}/rest'

# personal tag telling nattka to leave a bug alone
SKIP_TAG = 'nattka:skip'

__all__ = [
    'BUGZILLA_API_URL',
    'SKIP_TAG',
    'make_bugzilla',
    'split_dependent_bugs',
]


def make_bugzilla(api_key: typing.Optional[str],
                  endpoint: typing.Optional[str] = None,
                  **kwargs: typing.Any
                  ) -> Bugzilla:
    """
    Build a client for `endpoint`, defaulting to bugs.gentoo.org

    nattka has always spelled the endpoint with the ``/rest`` suffix, which
    the client appends itself, so it is accepted either way.
    """

    base_url = (endpoint or BUGZILLA_API_URL).rstrip('/').removesuffix('/rest')
    return Bugzilla(api_key,
                    base_url=base_url,
                    user_agent=f'nattka/{__version__}',
                    **kwargs)


def split_dependent_bugs(bugdict: typing.Dict[int, Bug],
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
        for b in curbug.depends_on:
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
