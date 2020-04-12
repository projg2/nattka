============
Introduction
============

What is NATTkA?
===============
NATTkA is a toolkit for dealing with keywording and stabilization bugs
in Gentoo.  It replaces an earlier tool called *stable-bot*.  Its
primary goal is to verify that all keyword and stabilization requests
are complete and correct, and to make it easy to apply them on arch
tester's systems.


History
=======
In the December of 2016, Agostino Sarubbo and Michael Palimaka
`revolutionalized stabilization process`_ in Gentoo.  Before their
effort, keywording and stabilization were requested via regular bugs.
Devlopers indicated the target packages somewhere on the bug (in summary
and/or comments), arch teams copied that list and worked on it.  All
the preparations needed to be done manually, and if the package list
turned out wrong (e.g. because of missing dependencies), arch teams
had to engage in additional effort to get them corrected.

Their changes made keywording and stabilization bugs machine-readable.
This new feature was utilized by a tool called *stable-bot* that
verified all new requests, and reported whether the package lists had
all dependencies satisfied.  Now developers could learn about their
mistake and fix the list before arch teams started working on it.  This
also meant that arch teams could now automatically obtain complete
(verified) package lists without having to manually find and copy them.

Over time, stable-bot maintenance seems to have ceased.  Gentoo
Developers met with frustrating bugs and limitations (e.g. having to
keep manually updating versions on keywording requests).  The stable-bot
owner repeatedly delayed releasing the source code, making it both
impossible to fix it and rendering the software effectively proprietary.

NATTkA was eventually created as an effort to rewrite stable-bot from
scratch.  From day zero it started as an open source project with high
test coverage, initially aimed at becoming a drop-in replacement for
stable-bot sanity checks with minimal bug fixes but eventually to start
implementing new incompatible features to make developer lives easier.

.. _revolutionalized stabilization process:
   https://archives.gentoo.org/gentoo-dev/message/4b2ef0e9aa7588224b8ae799c5fe31fa


Primary features
================
The primary advantages of NATTkA over stable-bot are:

- *Speed*: sanity checks are done using pkgcheck_ which is much faster
  than repoman.

- *Ability to test before CC-ing arches*: stable-bot tests bugs only
  when arches are CC-ed, NATTkA does it immediately if keywords
  are fully provided on the package list.

- *Periodic bug rechecks*: stable-bot rechecks bug only when requested
  or package list changes, NATTkA periodically verifies that the lists
  are still up-to-date.

- *Smarter dealing with keywordreqs and stablereqs*: stable-bot requires
  you to get everything right, or it may try to downgrade stable
  packages to ``~arch``.  NATTkA ignores requests for package-arch
  combinations that have matching or better keyword already.

- *Relaxed package specifications for keywording*: stable-bot requires
  you to specify exact versions of keyworded packages.  This results
  in a need to update keywording bugs often, and sometimes in arch teams
  keywording old versions instead of the newest.  With NATTkA, generic
  package dependency specifications are permitted.

- *New keyword tokens that ease common tasks*: stable-bot can only
  infer keywords from CC, and requires you to type them explicitly
  otherwise.  NATTkA extends the package list syntax to support
  additional tokens: ``^`` to copy keywords from the previous package
  on the list, ``*`` to align keywords to other versions.

- *Better handling of problematic dependencies*: stable-bot tended
  to ignore problematic dependencies.  NATTkA ignores them only when
  the package list is clearly empty or processed arches render them
  irrelevant, and otherwise explicitly informs the developer that
  a blocking bug is causing an issue.

.. _pkgcheck: https://github.com/pkgcore/pkgcheck/
