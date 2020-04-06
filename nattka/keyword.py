# (c) 2020 Michał Górny
# 2-clause BSD license

""" Minimal keyword mangling routines. """

import datetime
import re
import typing

from pathlib import Path

from snakeoil.fileutils import AtomicWriteFile


COPYRIGHT_RE = re.compile(
    r'^(?P<pre>.*\bCopyright )(?P<year1>(?:[0-9]{4}-)?)(?P<year2>[0-9]{4})'
    r'(?P<owner> Gentoo (?:Foundation|Authors)\b)(?P<post>.*)$',
    re.DOTALL)

KEYWORDS_RE = re.compile(
    r'^(?P<pre>[^#]*\bKEYWORDS=(?P<quote>[\'"]?))'
    r'(?P<keywords>.*)'
    r'(?P<post>(?P=quote).*)$')


class KeywordsNotFound(Exception):
    pass


def keyword_sort_key(kw: str
                     ) -> typing.Tuple[str, ...]:
    """
    Return the keyword sorting key, i.e. sort by os, then arch name.
    """
    return tuple(reversed(kw.lstrip('-~').partition('-')))


def update_copyright(copyright_line: str,
                     target_year: int = datetime.datetime.utcnow().year,
                     ) -> str:
    """
    Update copyright date and owner in `copyright_line`.
    """

    m = COPYRIGHT_RE.match(copyright_line)
    if m is not None:
        pre, y1, y2, owner, post = m.groups()
        year = str(target_year)
        if not y1 and y2 != year:
            y1 = y2 + '-'
        y2 = year
        if owner == ' Gentoo Foundation':
            owner = ' Gentoo Authors'
        copyright_line = ''.join((pre, y1, y2, owner, post))
    return copyright_line


def update_keywords(keywords: typing.List[str],
                    new_keywords: typing.Iterable[str],
                    stable: bool
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


def update_keywords_in_file(path: Path,
                            keywords: typing.Iterable[str],
                            stable: bool
                            ) -> None:
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

    # update copyright if necessary
    data[0] = update_copyright(data[0])

    with AtomicWriteFile(path) as f:
        f.writelines(data)
