# Copyright 2020 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=7

DESCRIPTION="Dependency Test Case"
HOMEPAGE="https://github.com/mgorny/nattka/"

LICENSE="none"
SLOT="0"
KEYWORDS="~amd64"
IUSE="foo bar"

RDEPEND="
	foo? (
		dep/a:=
		|| (
			dep/b
			( <dep/c-10 dep/d )
		)
	)
	bar? (
		dep/b
		dep/c
	)"
