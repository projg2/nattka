# (c) 2020 Michał Górny
# 2-clause BSD license

""" Tests for keyword mangling. """

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from nattka.keyword import (update_copyright, update_keywords,
                            update_keywords_in_file)


class UpdateCopyrightTests(unittest.TestCase):
    """Tests for update_copyright() function."""

    def test_not_a_copyright(self):
        self.assertEqual(
            update_copyright('foo bar baz', 2015),
            'foo bar baz')

    def test_up_to_date_single(self):
        self.assertEqual(
            update_copyright('# Copyright 2015 Gentoo Authors', 2015),
            '# Copyright 2015 Gentoo Authors')

    def test_up_to_date_range(self):
        self.assertEqual(
            update_copyright('# Copyright 1999-2015 Gentoo Authors', 2015),
            '# Copyright 1999-2015 Gentoo Authors')

    def test_old_single(self):
        self.assertEqual(
            update_copyright('# Copyright 2012 Gentoo Authors', 2015),
            '# Copyright 2012-2015 Gentoo Authors')

    def test_old_range(self):
        self.assertEqual(
            update_copyright('# Copyright 1999-2012 Gentoo Authors', 2015),
            '# Copyright 1999-2015 Gentoo Authors')

    def test_old_owner(self):
        self.assertEqual(
            update_copyright('# Copyright 1999-2015 Gentoo Foundation', 2015),
            '# Copyright 1999-2015 Gentoo Authors')


class UpdateKeywordsTests(unittest.TestCase):
    """ Tests for update_keywords() function. """

    def test_new_stable_keywords(self):
        """ Test adding new stable keywords to an empty list. """
        self.assertEqual(
            update_keywords([], ['x86', 'amd64'], stable=True),
            ['amd64', 'x86'])

    def test_new_testing_keywords(self):
        """ Test adding new testing keywords to an empty list. """
        self.assertEqual(
            update_keywords([], ['x86', 'amd64'], stable=False),
            ['~amd64', '~x86'])

    def test_add_stable_keywords(self):
        """ Test adding stable keywords to other keywords. """
        self.assertEqual(
            update_keywords(['arm', '-sparc', '~alpha'], ['x86', 'amd64'],
                            stable=True),
            ['~alpha', 'amd64', 'arm', '-sparc', 'x86'])

    def test_add_testing_keywords(self):
        """ Test adding testing keywords to other keywords. """
        self.assertEqual(
            update_keywords(['arm', '-sparc', '~alpha'], ['x86', 'amd64'],
                            stable=False),
            ['~alpha', '~amd64', 'arm', '-sparc', '~x86'])

    def test_upgrade_to_stable(self):
        """ Test upgrading keywords from ~arch to stable. """
        self.assertEqual(
            update_keywords(['~arm', '-sparc', '~alpha'], ['arm'],
                            stable=True),
            ['~alpha', 'arm', '-sparc'])

    def test_noop_to_stable(self):
        """ Test trying to stabilize already-stable arch. """
        self.assertIsNone(
            update_keywords(['arm', '-sparc', '~alpha'], ['arm'],
                            stable=True))

    def test_upgrade_to_stable_from_negative(self):
        """ Test upgrading to stable from -arch. """
        self.assertEqual(
            update_keywords(['arm', '~alpha', '-sparc'], ['sparc'],
                            stable=True),
            ['~alpha', 'arm', 'sparc'])

    def test_noop_to_testing(self):
        """ Test trying to keyword already-keyworded arch. """
        self.assertIsNone(
            update_keywords(['arm', '-sparc', '~alpha'], ['alpha'],
                            stable=False))

    def test_noop_from_stable_to_testing(self):
        """ Test trying to keyword already-stabilized arch. """
        self.assertIsNone(
            update_keywords(['arm', '-sparc', '~alpha'], ['arm'],
                            stable=False))

    def test_upgrade_to_testing_from_negative(self):
        """ Test upgrading to testing from -arch. """
        self.assertEqual(
            update_keywords(['arm', '~alpha', '-sparc'], ['sparc'],
                            stable=False),
            ['~alpha', 'arm', '~sparc'])

    def test_sorting(self):
        """ Test correct sorting of various keywords. """
        self.assertEqual(
            update_keywords(['arm', '-sparc', '~alpha', '~x86-fbsd',
                             '~amd64-linux'],
                            ['amd64-fbsd', 'amd64-macos', 'hppa',
                             'arm64'],
                            stable=False),
            ['~alpha', 'arm', '~arm64', '~hppa', '-sparc',
             '~amd64-fbsd', '~x86-fbsd', '~amd64-linux', '~amd64-macos'])

    def test_cleanup_redundant(self):
        """ Test that redundant keywords are removed. """
        self.assertEqual(
            update_keywords(['-alpha', '~alpha',
                             '-arm',
                             '-arm64', '~arm64',
                             '-hppa', '~hppa', 'hppa',
                             '~sparc',
                             '-x86', 'x86'],
                            ['arm', 'arm64', 'sparc'], stable=True),
            ['~alpha', 'arm', 'arm64', 'hppa', 'sparc', 'x86'])


@patch('nattka.keyword.update_copyright',
       lambda l: update_copyright(l, 2015))
class UpdateKeywordsInFileTests(unittest.TestCase):
    """ Tests for update_keywords_in_file() function. """

    copyright = '# Copyright 1999-2012 Gentoo Foundation'
    new_copyright = '# Copyright 1999-2015 Gentoo Authors'
    ebuild_header = '''# Fancy Gentoo ebuild
# with some comment on top

EAPI=7

inherit some-eclass

DESCRIPTION="blah blah"
HOMEPAGE="https://example.com"
SRC_URI=""

LICENSE=""
SLOT="0"
'''

    ebuild_footer = '''
RDEPEND="test/package"

src_configure() {
    emake KEYWORDS="123"
}
'''

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def write_ebuild(self, keywords_line: str) -> Path:
        """
        Write ebuild template along with specified @keywords_line.
        Returns the path to the newly-written file.
        """
        fn = Path(self.tempdir.name) / 'test-1.ebuild'
        with open(fn, 'w') as f:
            f.write(f'''{self.copyright}
{self.ebuild_header}
{keywords_line}
{self.ebuild_footer}''')
        return fn

    def check_ebuild(self, fn: Path, keywords_line: str) -> None:
        """
        Check whether ebuild @fn was modified correctly, i.e. header/
        footer was preserved and KEYWORDS line was changed
        to @keywords_line.
        """
        with open(fn, 'r') as f:
            data = f.read()
        self.assertEqual(data, f'''{self.new_copyright}
{self.ebuild_header}
{keywords_line}
{self.ebuild_footer}''')

    def test_double_quotes(self):
        """ Test on a file with double-quoted KEYWORDS. """

        fn = self.write_ebuild('KEYWORDS="~amd64 ~x86"')
        update_keywords_in_file(fn, ['amd64', 'arm'], stable=True)
        self.check_ebuild(fn, 'KEYWORDS="amd64 arm ~x86"')

    def test_single_quotes(self):
        """ Test on a file with single-quoted KEYWORDS. """

        fn = self.write_ebuild("KEYWORDS='~amd64 ~x86'")
        update_keywords_in_file(fn, ['amd64', 'arm'], stable=True)
        self.check_ebuild(fn, "KEYWORDS='amd64 arm ~x86'")

    def test_nonquoted_keywords(self):
        """ Test on a file with KEYWORDS without quotes. """

        fn = self.write_ebuild('KEYWORDS=amd64')
        update_keywords_in_file(fn, ['arm', 'x86'], stable=False)
        self.check_ebuild(fn, 'KEYWORDS="amd64 ~arm ~x86"')

    def test_empty_keywords(self):
        """ Test on a file with KEYWORDS assigned empty value. """

        fn = self.write_ebuild('KEYWORDS=""')
        update_keywords_in_file(fn, ['arm', 'x86'], stable=False)
        self.check_ebuild(fn, 'KEYWORDS="~arm ~x86"')

    def test_nonquoted_empty_keywords(self):
        """
        Test on a file with KEYWORDS assigned empty value,
        without quotes.
        """

        fn = self.write_ebuild('KEYWORDS=')
        update_keywords_in_file(fn, ['arm', 'x86'], stable=False)
        self.check_ebuild(fn, 'KEYWORDS="~arm ~x86"')

    def test_whitespace(self):
        """
        Test on a file with KEYWORDS preceded by whitespace (indented).
        """

        fn = self.write_ebuild('\t  KEYWORDS="~amd64 ~x86"')
        update_keywords_in_file(fn, ['amd64', 'arm'], stable=True)
        self.check_ebuild(fn, '\t  KEYWORDS="amd64 arm ~x86"')

    def test_conditional(self):
        """
        Test on a file with KEYWORDS assigned conditionally.
        """

        fn = self.write_ebuild(
            '[[ ${PV} != 9999 ]] && KEYWORDS="~amd64 ~x86"')
        update_keywords_in_file(fn, ['amd64', 'arm'], stable=True)
        self.check_ebuild(
            fn, '[[ ${PV} != 9999 ]] && KEYWORDS="amd64 arm ~x86"')
