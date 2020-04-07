===========
Quick start
===========

Dependencies
============
NATTkA requires the following native programs:

- Python_ 3.6 or newer.
- git_ version control system.

NATTkA interacts against a running Bugzilla instance.  It requires
Bugzilla 5.1 or 5.0 with backported ``whoami`` endpoint (e.g. found
in `Gentoo Bugzilla code`_).

Additionally, it requires the following Python packages (that can
be installed inside a virtualenv):

- pkgcore_ package manager and pkgcheck_ linting tool.
- requests_ HTTP library.

Running tests additionally requires:

- vcrpy_ replay HTTP request mocking library.

pytest_ is strongly recommended but the tests are compatible with
standard unittest runner (but they are quite noisy).

.. _Python: https://www.python.org/
.. _git: https://git-scm.com/
.. _Gentoo Bugzilla code: https://gitweb.gentoo.org/fork/bugzilla.git
.. _pkgcore: https://github.com/pkgcore/pkgcore/
.. _pkgcheck: https://github.com/pkgcore/pkgcheck/
.. _requests: http://python-requests.org/
.. _vcrpy: https://vcrpy.readthedocs.io/
.. _pytest: https://pytest.org/


Bugzilla API key
================
Read-write operations on Bugzilla require using an API key.  It is also
recommended for read-only operations as otherwise Bugzilla strips e-mail
addresses in CC.

A new API key can be generated in `API Keys`_ tab of Bugzilla
preferences.  Once generated, it can be either pass via command-line
``--api-key`` option or stored in ``~/.bugz_token`` file (plain text
file containing the API key as its only line, compatible with old
versions of pybugz).

Note that when using NATTkA in read-write mode, it is recommended
to create a dedicated Bugzilla account.

.. _API Keys: https://bugs.gentoo.org/userprefs.cgi?tab=apikey


Gentoo git repository
=====================
The main keywording/stabilization request testing mode requires a git
repository to work in.  Normally this should be the original gentoo.git_
repository.  However, it is entirely valid to use an equivalent
repository (e.g. the sync repository) or even create a dummy repository
on top of another ebuild repository checkout.

The working tree needs to be clean, i.e. have no unstaged changes.
NATTkA writes to the files in repository directly, then uses ``git
checkout`` to restore their original contents.

.. _gentoo.git: https://gitweb.gentoo.org/repo/gentoo.git/


Using NATTkA for arch testing
=============================

Applying keyword changes
------------------------
The ``nattka apply`` command is designed to help arch testers grab
packages from keywording and stabilization requests, and apply them
to the local repository.

To process a specific bug::

    nattka apply 123456...

To find all bugs of specific type::

    nattka apply --keywordreq
    nattka apply --stablereq
    nattka apply --security

To run for another arch::

    nattka apply -a arm64 ...
    nattka apply -a hppa -a sparc ...
    nattka apply -a '*' ...

If you do not wish it to modify the local repository but only print
package list with keywords::

    nattka apply -n ...

If you wish not to skip bugs that did not pass sanity-check or have
unresolved dependencies::

    nattka apply --ignore-sanity-check ...
    nattka apply --ignore-dependencies ...


Actual testing
--------------
NATTkA defers the task of testing packages to other tools.


Committing
----------
Once packages are tested, ``commit`` command may be used to commit
(previously applied) keyword changes::

    nattka commit [-a ...] 123456

Note that you need to specify bug numbers explicitly, and the same
``-a`` value as for ``apply`` (this will be autodetected in the future).

The commits are *not* pushed instantly.  You should remember to rerun
linting tools before pushing, e.g.::

    pkgcheck scan --commits
    git push --signed


Processing bugs
===============
The recommended way to run NATTkA is to run it via cronjob, using
the following options::

    nattka --repo <path-to-repo> process-bugs \
        --cache-file <path-to-cache-file> \
        --time-limit 600 \
        --update-bugs

The ``--repo`` option specifies where the git checkout of the ebuild
repository is to be found.

``--cache-file`` is used to store previous check results.  When it is
used, the checks are rerun every 12 hours rather than on every run.

``--time-limit`` indicates that NATTkA should terminate after
10 minutes.  This ensures that NATTkA does not spend too much time
rechecking old bugs.  With cronjob set e.g. to 15 minutes, it ensures
that new bugs are processed timely.

Finally, ``--update-bugs`` enables writing to Bugzilla.  You can omit
it to test NATTkA in pretend mode.
