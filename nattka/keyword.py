# (c) 2020 Michał Górny
# 2-clause BSD license

""" Minimal keyword mangling routines. """

import re
import typing

from pathlib import Path


KEYWORDS_RE = re.compile(
    r'^(?P<pre>[^#]*\bKEYWORDS=(?P<quote>[\'"]?))'
    r'(?P<keywords>.*)'
    r'(?P<post>(?P=quote).*)$')


class KeywordsNotFound(Exception):
    pass


def keyword_sort_key(kw):
    """
    Return the keyword sorting key, i.e. sort by os, then arch name.
    """
    return tuple(reversed(kw.lstrip('-~').partition('-')))


def update_keywords(keywords: typing.List[str],
        new_keywords: typing.Iterable[str], stable: bool
        ) -> typing.Optional[typing.List[str]]:
    """
    Update list of keywords @keywords using @new_keywords.  @stable
    specifies whether new keywords should be stable or ~arch.  ~arch
    keywords *do not* overwrite stable keywords, both stable and ~arch
    keywords overwrite negative (-*) keywords.  Returns the updated
    list or None, if no updates.
    """

    orig_kw = frozenset(keywords)
    kw = set(orig_kw)
    # first add new keywords
    for k in new_keywords:
        kw.add(k if stable else f'~{k}')
    # then remove all redundant keywords
    for k in list(kw):
        # remove -kw if ~kw or kw is present
        kw.discard(f'-{k.lstrip("~")}')
        # remove ~kw if kw is present
        kw.discard(f'~{k}')

    if kw != orig_kw:
        return sorted(kw, key=keyword_sort_key)
    return None


def update_keywords_in_file(path: Path, keywords: typing.Iterable[str],
        stable: bool) -> None:
    """
    Update KEYWORDS entry in the file at @path.  @keywords specifies
    a list of keywords, @stable indicates whether they should be stable
    or ~arch.

    Raises KeywordsNotFound if no suitable KEYWORDS variable is found.
    """

    with open(path, 'r') as f:
        data = f.readlines()

    for i, l in enumerate(data):
        m = KEYWORDS_RE.match(l)
        if m is None:
            continue

        kw = update_keywords(m.group('keywords').split(),
                             keywords, stable=stable)
        if kw is None:
            # no update?
            return

        new_kw = ' '.join(kw)
        # add quotes if there were none before
        if not m.group('quote'):
            new_kw = f'"{new_kw}"'
        data[i] = f'{m.group("pre")}{new_kw}{m.group("post")}\n'
        break

    # TODO: use atomic updates
    with open(path, 'w') as f:
        f.writelines(data)
