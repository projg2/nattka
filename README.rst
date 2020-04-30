===================================
NATTkA -- A New Arch Tester Toolkit
===================================
:Author: Michał Górny
:License: 2-clause BSD license
:Homepage: https://github.com/mgorny/nattka/
:Documentation: https://dev.gentoo.org/~mgorny/doc/nattka/


NATTkA is a combined replacement for Gentoo keywordreq/stablereq sanity
checking tool stable-bot, and its client ``getatoms.py``.  It is meant
to make preparing and processing keywording bugs more consistent
and easier.  NATTkA specifically focuses on activity relevant to
Bugzilla — verifying bugs, getting package lists, committing changes
(based on bugs ☺) and closing bugs.


Features
========
The primary features of NATTkA are:

- Fast sanity checking of requests using pkgcheck_ backend, even
  if arches are not CC-ed yet (if keywords can be determined
  from package list).

- Support for generic package dependency syntax in package list field
  for keywording requests, removing the requirement to explicitly
  specify one package version and keep it updated.

- ``apply`` command that replaces ``getatoms.py``, with support for
  applying keywords in place and dependency sort of output.

- ``commit`` command that takes care of committing keyworded packages
  with automatically generated commit messages.

- ``resolve`` command that takes care of unCC-ing arches from bugs,
  and closing them if appropriate.

- Automatic CC-ing of the correct arch teams via ``CC-ARCHES`` keyword.

- Support for ALLARCHES stabilizations.


Filing keywording/stabilization bugs
====================================
NATTkA uses the same Bugzilla features as stable-bot.  It processes
bugs filed in keywording/stabilization-related components, with package
list field filled in.  The results of sanity check are reported via flag
and comment on the bug.

Package list names one package per line (using CPV or package dependency
specification form), optionally followed by one or more keywords.

For stabilization requests, exact package versions must be specified.
For keywording requests, generic specifications can be used instead.
If they match multiple versions, the program will determine the newest
suitable version.

Tilde before keywords is optional and does not influence the behavior —
stable or testing keywords are used depending on component used.
If keywords are listed for all packages, the bug can be checked even
before arch teams are CC-ed.

In place of explicit (or implicit) keywords, additional tokens can
be used to save typing:

- ``^`` that copies keywords from the previous package on the list.

- ``*`` that aligns keywords to other versions of the package.

Once arch teams are CC-ed, effective keywords are determined
as the intersection of specified keywords and CC-ed arches.  Packages
listed without keywords are assumed to be requested on all CC-ed arches.

Alternatively to CC-ing arch teams, the ``CC-ARCHES`` keyword can be
added to a bug.  In that case, NATTkA will automatically determine arch
teams from the package list field and CC them, as long as the bug passes
sanity check.

NATTkA scans package ``metadata.xml`` files for ``stabilize-allarches``
element.  If all packages on the package list have one, it automatically
adds ``ALLARCHES`` keyword.  Otherwise, it ensures that this keyword
is not present.

Example package list follows::

    dev-bar/libfrobnicate-9.0
    dev-foo/frobnicate-1.2.3 amd64 x86
    dev-libs/libdependency-7.7.7 ^

Detailed information on Bugzilla use can be found in the `bug
processing`_ section of the documentation.


Basic usage help
================
NATTkA uses Python's argument parser with subcommand support.  To get
help on global options and available commands, type::

    nattka --help

To get help on command-specific arguments, type::

    nattka <subcommand> --help

Please note that global options *must* be passed before the command,
and command-specific options after it.

Detailed help on command-line options can be found in the usage_ section
of the documentation.


Using NATTkA for arch testing
=============================
The following workflow assumes that you are working on ``gentoo.git``
repository clone, and running NATTkA inside the checkout.  You should
generate API key and put it in ``~/.bugz_token`` file (as used by old
versions of pybugz) or pass via ``--api-key`` global option.

First, use the ``apply`` command to get some pending bugs and apply
their keywords to your local checkout.

To process a specific bug, pass its number::

    nattka apply 123456 123458

To find and process all open bugs, run the command without
any arguments::

    nattka apply

Search results can further be narrowed::

    nattka apply --keywordreq
    nattka apply --stablereq
    nattka apply --security

To run for another arch than host's::

    nattka apply -a arm64 ...
    nattka apply -a hppa -a sparc ...
    nattka apply -a '*' ...

To disable modifying keywords on packages and just output a list
suitable for copying into ``package.accept_keywords``::

    nattka apply -n ...

To disable skipping bugs that did not pass sanity check or have
unresolved dependencies::

    nattka apply --ignore-sanity-check ...
    nattka apply --ignore-dependencies ...

To disable performing ``ALLARCHES`` stabilizations::

    nattka apply --ignore-allarches ...

After successfully testing the packages, use ``commit`` command
to commit the changes::

    nattka commit [-a ...] [--ignore-allarches] 123456

Then check and push them::

    pkgcheck scan --commits
    git push --signed

Finally, update the bugs::

    nattka resolve [-a ...] [--ignore-allarches] 123456

A little more details can be found in the `quick start`_ section
of the documentation.


.. _pkgcheck: https://github.com/pkgcore/pkgcheck/
.. _bug processing: https://dev.gentoo.org/~mgorny/doc/nattka/bug.html
.. _usage: https://dev.gentoo.org/~mgorny/doc/nattka/usage.html
.. _quick start: https://dev.gentoo.org/~mgorny/doc/nattka/quickstart.html
