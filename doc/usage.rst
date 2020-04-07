=====
Usage
=====

.. highlight:: none


Commands
========
NATTkA exposes its functions as sub-commands of the ``nattka``
executable.  The basic usage is:

.. code-block::

    nattka [<global options>...] <command> [<command arguments>...]

The following commands are supported:

apply
   Applies keywords from specified bugs to the working tree.

commit
   Commits previously applied keyword changes to git (does not push).

process-bugs
   Perform sanity checks of specified bugs — fetch keywords, apply
   them to the local checkout, run ``pkgcheck`` and update the bugs
   if requested.


Global options
==============
Global options are common to all commands.  They must be specified
*before* the command.


Logging control
---------------
Normally NATTkA prints verbose progress messages to the console.

If this is undesirable, ``-q`` (``--quiet``) option can be used to
silence the output.  Only critical failures preventing the program
from starting and Python tracebacks on unexpected exceptions will
be printed.

Alternatively, ``--log-file`` can be used to direct verbose logs
into the specified file.  If the specified file exists already, logs
will be appended to it.  Critical failures and Python tracebacks
will still be printed to the console.


Bugzilla configuration
----------------------
It is strongly recommended to generate Bugzilla API key and use it
for Bugzilla communications.  While it is possible to perform
read-only actions anonymously, the returned data will not contain
full e-mail addresses and will therefore be prone to mistakes.

The API key can be passed as ``--api-key`` option, or stored
in ``~/.bugz_token`` file.  The former option overrides the latter file,
if both are present.

NATTkA uses Gentoo Bugzilla by default.  Another Bugzilla instance
can be used by specifying ``--api-endpoint``.  It should contain full
URL to the REST API endpoint, i.e. with ``/rest`` suffix.


Repository configuration
------------------------
NATTkA assumes it is run within the ebuild repository by default.
If this is not the case, the path to the repository can be specified
using ``--repo`` option.

Normally, NATTkA uses default system configs for the package manager.
``--portage-conf`` option can be used to override this configuration
directory and use another Portage-style configuration directory.  This
directory needs to contain at least ``make.profile`` symlink.


apply command
=============

Basic usage
-----------
The ``apply`` command is used to apply keywords from a keywording
or stabilization bug to the local checkout, and print the list for
arch tester's use.

NATTkA works for the system arch (as defined by the pkgcore/Portage
config) by default.  To work for another arch, pass it via ``-a``
(``--arch``) option.  The option can be repeated and wildcards can
be used to specify multiple targets, in particular ``*`` enables
all known arches.

If you do not wish for NATTkA to apply keywords locally, and just print
the list for you, pass ``-n`` (``--no-update``).

Specific bug numbers can be specified as positional arguments
to the command, e.g.::

    nattka apply 123456 123460

Alternatively, if no numbers are specified NATTkA finds all open
keywording and stabilization bugs.


Filtering bugs
--------------
In both cases, additional options can be used to further filter
the results.  In general, separate conditions are combined using AND
operator (i.e. only bugs matching all of them are returned), while
different values for the same group of conditions are OR-ed together
(i.e. all bugs having one of the values are processed).

``--keywordreq`` limits processing to keywording requests, while
``--stablereq`` limits it to stabilization requests.  Additionally,
``--security`` option can be used to limit results to security bugs.

Normally, NATTkA applies keywords only when the bug in question passed
sanity-check.  To disable this filter and process any bugs, pass
``--ignore-sanity-check``.

NATTkA fetches dependencies of all bugs automatically.  If this is
undesirable, it can be disabled using ``--no-fetch-dependencies``.

Any bug having unresolved dependencies is skipped.  To ignore unresolved
dependencies, use ``--ignore-dependencies``.  The recommended approach
is to process and commit the dependencies first, and rerun the ``apply``
command once the blocking bug is marked fixed.


Output
------
The ``apply`` command output is suitable for copying straight into
the ``package.accept_keywords`` file.  Additional information such as
bug numbers, issues and target keywords for keyword requests are output
as comments.

Example output::

    # bug 701300 (KEYWORDREQ)
    =app-admin/mongo-tools-4.2.2 **  # -> ~arm64
    =dev-python/cheetah3-3.2.3 **  # -> ~arm64
    =dev-db/mongodb-4.2.2 **  # -> ~arm64

    # bug 700918: sanity check failed

    # bug 700806 (STABLEREQ)
    =net-mail/mailutils-3.8 ~arm64

    # bug 699838: unresolved dependency on 706146, 706442


commit command
==============
The ``commit`` command is used to commit keyword changes to the git
repository.  It should be used after ``apply``.  It takes care of using
the correct package list and making reasonably good commit messages.

At the moment, the ``commit`` command does not autodetect which keywords
were changed.  Instead, you need to pass the same ``--arch`` options
as to ``apply``.

Specific bug numbers must be specified as positional arguments
to the command, e.g.::

    nattka commit -a arm64 123456 123460


process-bugs command
====================

Basic usage
-----------
The ``process-bugs`` command is used to perform sanity checks of open
keywording and stabilization bugs.

The normal way of using it is to omit positional arguments, causing it
to process all open keywording and stabilization bugs::

    nattka process-bugs

Alternatively, specific bug numbers can be passed in order to limit
the operation to them::

    nattka process-bugs 123456 123460


Filtering bugs
--------------
In both cases, additional options can be used to further filter
the results.  In general, separate conditions are combined using AND
operator (i.e. only bugs matching all of them are returned), while
different values for the same group of conditions are OR-ed together
(i.e. all bugs having one of the values are processed).

``--keywordreq`` limits processing to keywording requests, while
``--stablereq`` limits it to stabilization requests.  Additionally,
``--security`` option can be used to limit results to security bugs.

NATTkA fetches dependencies of all bugs automatically.  If this is
undesirable, it can be disabled using ``--no-fetch-dependencies``.
Note that bugs with unsatisfied dependencies will be skipped to avoid
reporting false positives.


Limiting processing
-------------------
Normally, NATTkA processes all bugs specified on the command line
or found on Bugzilla.  This can result in very long run times, and when
run repeatedly it can cause delays in processing new bugs.

The ``--bug-limit`` option takes a number of bugs to be checked.  It can
be used to cause the program to terminate after processing this many
bugs, opening the possibility of starting it again to tackle newly filed
bugs.  Only bugs actually processed by ``pkgcheck`` are counted towards
the limit (i.e. not bug skipped).

The ``--time-limit`` option takes maximum run time in seconds.
Once the program runs for specified time, it gracefully exits after
processing the current bug.


Caching
-------
By default, NATTkA retests all specified bugs.  This is not strictly
a problem since bugs are updated only if the new status differs
from the last status reported to the bug.  However, with large number
of bugs open it can cause every program run to last very long.

Caching can be used to resolve that problem.  It can be enabled via
passing ``-c`` (``--cache-file``) option along with a path to a JSON
cache file (it will be created it if it does not exist).

When cache is enabled, NATTkA stores check results along with bug
information (package lists, sanity-check flag) in it.  When it is run
again, it verifies whether the cache entry is up-to-date (i.e. the bug
has not changed and the entry has not expired) and skips rechecking
packages where it is unnecessary.

Combined with ``--bug-limit`` or ``--time-limit``, cache makes it
possible to restart NATTkA often while permitting it to combine quick
processing of newly filed bugs with periodically rechecking historical
bugs.

``--cache-max-age`` option can be used to specify how often bugs should
be rechecked, in seconds.  The default value amounts to 12 hours.


Bug updates
-----------
For safety reasons, bug processing is normally run in ‘pretend mode’.
Bugs are checked for correctness but the results are only output
to console (logs).  If you are ready to run it in production and enable
posting to bugs, append ``-u`` (``--update-bugs``).

Please note that this requires an API key to be present.  It is strongly
recommended that this API key belongs to a separate account used only
by NATTkA.
