# Copyright 2020 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=7

DESCRIPTION="Dependency Test Case"
HOMEPAGE="https://github.com/mgorny/nattka/"

LICENSE="none"
SLOT="0"
KEYWORDS="~amd64"

RDEPEND="dep/h"
DEPEND="test? ( dep/h )"
PDEPEND="dep/f"
