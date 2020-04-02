==============
Bug processing
==============

Bug categories
==============
There are two categories of bugs processed by NATTkA: keyword requests,
and stabilization requests.  The bug category is determined from
the product and component that it is filled in.

- Bugs filed in *Gentoo Linux* product, *Keywording* component are
  keywording requests.

- Bugs filed in *Gentoo Linux* product, *Stabilization* component are
  stabilization requests.

- Bugs filed in *Gentoo Security* product, *Kernel* or *Vulnerabilities*
  component are stabilization requests.

Bugs filed in any other product or component are skipped.


Package lists
=============
The package list field is used to specify packages to be keyworded
or stabilized.  Each non-empty line contains a package specification,
followed by zero or more keywords, delimited by any amount
of whitespace.  Leading and trailing whitespace is ignored as well.

A package specification can be either the so-called CPV form
(``<cat>/<package>-<version>``) or a subset of package dependency
specification.  In the latter case, only non-wildcard ``=`` dependencies
without slots, USE dependencies and other extensions are allowed.

A keyword is one of the arch names, optionally prefixed by a tilde
(``~``).  Note that the tilde is ignored, and stable or testing keywords
are applied depending on the bug category.  If no keywords are
specified, they are inferred from the arch teams found in CC.

.. code-block::
   :caption: Example package list

   app-misc/frobnicate-1.2.3 amd64 x86
   =dev-libs/libfrobnicate-1.9


Sanity check flag
=================
The *sanity-check* flag is used to store the current status of package
list checks.  It can have one of the three values: unset, true (``+``)
or false (``-``).

The flag is initially unset.  It is left unset or reset to unset state
if the package list is empty or keywords can not be fully determined,
i.e. the bug can not be checked at the moment.

The flag is set to ``+`` status if the check succeeds.  A comment
is added if the status changes from ``-`` to ``+``, otherwise no comment
is added.

The flag is set to ``-`` status if the check fails or the package data
is invalid.  A comment is added if the error message is different
from the last comment left by NATTkA.


Bug dependencies
================
Dependency fields (*Depends on* and *blocks*) can be used to indicate
blockers for keywording or stabilization of any package.

Blockers belonging to the same category indicate dependencies between
keywording or stabilization requests.  When checking the bug
in question, NATTkA applies keywords from its dependent bugs in order
to verify the package list.  However, only packages from the bug
in question are tested — i.e. a bug that fails sanity-check itself
may be sufficient to cause its reverse dependency to pass.

Blockers belonging to other category are treated as bugs preventing
keywording and stabilization from proceeding.
