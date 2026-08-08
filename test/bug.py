# (c) 2020-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

""" Building bugs for tests.

:class:`pkgcore.bugzilla.Bug` mirrors what Bugzilla returns, so the things
tests care about most are derived rather than stored: the category comes from
the product and component, sanity_check from the flags, security from the
product, and resolved from the resolution.  :func:`mk_bug` lets a test state
what it means and works the representation out.
"""

import datetime
import typing

from pkgcore.bugzilla import (Bug, BugCategory, BugUpdate, Comment,
                              FlagStatus, ListChange, NewComment, PackageList,
                              Product, Resolution, Status)
from pkgcore.bugzilla.bug import Flag
from pkgcore.bugzilla.wire import BugId, CommentId

# fields Bug stores as tuples, which tests are happier writing as lists
_SEQUENCES = ('cc', 'keywords', 'blocks', 'depends_on', 'alias', 'tags',
              'see_also', 'groups')


def mk_bug(category: typing.Optional[BugCategory] = None,
           packages: str = '',
           cc: typing.Iterable[str] = (),
           *,
           sanity_check: typing.Optional[bool] = None,
           security: bool = False,
           resolved: bool = False,
           depends: typing.Iterable[int] = (),
           **kwargs: typing.Any
           ) -> Bug:
    """
    Build a bug the way a test thinks about one

    `category` and `packages` map onto the product/component pair and the
    package list; `sanity_check`, `security` and `resolved` onto the flag,
    the product and the resolution.  `depends` is spelled `depends_on` on
    :class:`Bug`, and is accepted under both names.
    """

    if category is not None:
        kwargs.setdefault('product', str(category.product))
        kwargs.setdefault('component', str(category.component))
    if security:
        kwargs['product'] = str(Product.GENTOO_SECURITY)
    if resolved:
        kwargs.setdefault('resolution', 'FIXED')
    if sanity_check is not None:
        kwargs.setdefault('flags', (Flag(
            name='sanity-check',
            status=FlagStatus.GRANTED if sanity_check else FlagStatus.DENIED,
        ),))
    if depends:
        kwargs.setdefault('depends_on', depends)

    for key in _SEQUENCES:
        if key in kwargs:
            kwargs[key] = tuple(kwargs[key])

    return Bug(package_list=PackageList(packages), cc=tuple(cc), **kwargs)


def sanity_check_update(status: typing.Optional[bool],
                        comment: typing.Optional[str] = None,
                        cc_add: typing.Iterable[str] = (),
                        keywords_add: typing.Iterable[str] = (),
                        keywords_remove: typing.Iterable[str] = (),
                        new_package_list: typing.Iterable[str] = ()
                        ) -> BugUpdate:
    """
    The update nattka should issue for a sanity-check result

    Spelled in the terms the checks reason about, so a test states what nattka
    decided rather than how the payload is built.
    """

    return BugUpdate.sanity_check(
        status,
        comment=comment,
        cc=ListChange.adding(*cc_add),
        keywords=ListChange(add=tuple(keywords_add),
                            remove=tuple(keywords_remove)),
        package_list=(PackageList(''.join(new_package_list))
                      if new_package_list else None))


def resolve_update(uncc: typing.Iterable[str],
                   comment: str,
                   resolve: bool
                   ) -> BugUpdate:
    """The update nattka should issue when an arch is done with a bug"""

    return BugUpdate(
        status=Status.RESOLVED if resolve else Status.IN_PROGRESS,
        resolution=Resolution.FIXED if resolve else None,
        cc=ListChange.removing(*uncc),
        comment=NewComment(comment))


def mk_comment(text: str, creator: str = 'nattka@gentoo.org') -> Comment:
    """A comment, for stubbing out what the bug already says"""

    when = datetime.datetime(2020, 1, 1, 12, 0, 0,
                             tzinfo=datetime.timezone.utc)
    return Comment(id=CommentId(1), bug_id=BugId(560322), count=1, text=text,
                   creator=creator, creation_time=when)
