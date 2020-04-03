# (c) 2020 Michał Górny
# 2-clause BSD license

""" CLI for nattka. """

import argparse
import datetime
import json
import logging
import sys
import typing

from pathlib import Path

from snakeoil.fileutils import AtomicWriteFile
from pkgcore.ebuild.repository import UnconfiguredTree

from nattka import __version__
from nattka.bugzilla import (NattkaBugzilla, BugInfo, BugCategory,
                             get_combined_buginfo,
                             fill_keywords_from_cc)
from nattka.git import GitWorkTree, GitDirtyWorkTree
from nattka.package import (find_repository, match_package_list,
                            add_keywords, check_dependencies,
                            PackageNoMatch, KeywordNoMatch,
                            PackageInvalid)


log = logging.getLogger('nattka')


class SkipBug(Exception):
    pass


class NattkaCommands(object):
    args: argparse.Namespace
    bz: typing.Optional[NattkaBugzilla]
    repo: typing.Optional[UnconfiguredTree]

    def __init__(self,
                 args: argparse.Namespace):
        self.args = args
        self.bz = None
        self.repo = None

    def get_api_key(self,
                    require_api_key: bool = False
                    ) -> typing.Optional[str]:
        """
        Find and return the Bugzilla API key.  Raises SystemExit
        if unsuccesful.
        """

        if self.args.api_key is not None:
            return self.args.api_key
        try:
            with open(Path.home() / '.bugz_token', 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            pass
        if require_api_key:
            log.critical('Please pass --api-key or put it in ~/.bugz_token')
            raise SystemExit(1)
        else:
            log.warning('No API key provided, will run unauthorized queries')
            log.warning('(pass --api-key or put it in ~/.bugz_token)')
            return None

    def get_bugzilla(self,
                     require_api_key: bool = False
                     ) -> NattkaBugzilla:
        """
        Initialize and return a bugzilla instance.  Caches the result.
        If @require_api_key is True, requires API key to be provided.
        """

        if self.bz is None:
            # TODO: restore type checking once we get rid of auth
            kwargs: typing.Dict[str, typing.Any] = {}
            if self.args.bugzilla_auth is not None:
                kwargs['auth'] = tuple(self.args.bugzilla_auth.split(':', 1))
            if self.args.bugzilla_endpoint is not None:
                kwargs['api_url'] = self.args.bugzilla_endpoint
            self.bz = NattkaBugzilla(
                self.get_api_key(require_api_key=require_api_key),
                **kwargs)
        return self.bz

    def find_bugs(self) -> typing.Dict[int, BugInfo]:
        """
        Find/get bugs according to command-line options.  Returns
        a dictionary of bug numbers to BugInfo objects.
        """

        bz = self.get_bugzilla()
        if self.args.bug:
            bugs = bz.fetch_package_list(self.args.bug)
        else:
            bugs = bz.find_bugs(None)
        for bno, b in bugs.items():
            bugs[bno] = fill_keywords_from_cc(
                b, self.get_repository().known_arches)
        return bugs

    def get_repository(self) -> UnconfiguredTree:
        """
        Initialize and return a repo instance.  Caches the result.
        """

        if self.repo is None:
            self.repo = find_repository(self.args.repo,
                                        self.args.portage_conf)
        return self.repo

    def get_cache(self) -> dict:
        """
        Read cache file if specified.  Returns a deserialized cache
        or {} if not found.
        """

        if self.args.cache_file is not None:
            try:
                with open(self.args.cache_file, 'r') as f:
                    return json.load(f)
            except FileNotFoundError:
                pass
        return {}

    def write_cache(self, data: dict) -> None:
        """
        Write @data to the cache file, if one is specified.
        """

        if self.args.cache_file is not None:
            with AtomicWriteFile(self.args.cache_file) as f:
                json.dump(data, f, indent=2)

    def apply(self) -> int:
        repo = self.get_repository()
        for bno, b in self.find_bugs().items():
            if b.category is None:
                log.info(f'Bug {bno}: neither stablereq nor keywordreq')
                continue

            log.info(f'Bug {bno} ({b.category.name})')
            plist = dict(match_package_list(repo, b.atoms))

            if not plist:
                log.info('Skipping because of empty package list')
                continue
            if any(not x for x in plist.values()):
                log.info('Skipping because of incomplete keywords')
                continue

            for p, keywords in plist.items():
                log.info(f'Package {p.cpvstr}: {plist[p]}')
            add_keywords(plist.items(), b.category == BugCategory.STABLEREQ)

        return 0

    def process_bugs(self) -> int:
        repo = self.get_repository()
        git_repo = GitWorkTree(repo.location)
        if git_repo.path != Path(repo.location):
            log.critical(
                f'{repo.location} does not seem to be a git repository')
            raise SystemExit(1)

        if not self.args.update_bugs:
            log.warning(f'Running in pretend mode.')
            log.warning(f'(pass --update-bugs to enable bug updates)')

        cache = self.get_cache()
        cache.setdefault('bugs', {})

        bz = self.get_bugzilla(require_api_key=self.args.update_bugs)
        username = bz.whoami()
        bugs = self.find_bugs()
        log.info(f'Found {len(bugs)} bugs')
        bugs_done = 0
        end_time = None
        if self.args.time_limit is not None:
            end_time = (datetime.datetime.utcnow()
                        + datetime.timedelta(seconds=self.args.time_limit))
            log.info(f'Will process until {end_time}')

        try:
            # start with the newest bugs
            for bno in reversed(sorted(bugs)):
                if bugs_done > 0 and bugs_done % 10 == 0:
                    log.info(f'Tested {bugs_done} bugs so far')
                if self.args.bug_limit and bugs_done >= self.args.bug_limit:
                    log.info(f'Reached limit of {self.args.bug_limit} bugs')
                    break
                if (end_time is not None
                        and datetime.datetime.utcnow() > end_time):
                    log.info(f'Reached time limit')
                    break

                b = get_combined_buginfo(bugs, bno)
                if b.category is None:
                    log.info(f'Bug {bno}: neither stablereq nor keywordreq')
                    continue

                log.info(f'Bug {bno} ({b.category.name})')

                try:
                    comment: typing.Optional[str] = None
                    check_res: typing.Optional[bool] = None
                    cache_entry: typing.Optional[dict] = None

                    plist = dict(match_package_list(repo, b.atoms))
                    if not plist:
                        log.info('Skipping because of empty package list')
                        comment = ('Resetting sanity check; package list '
                                   'is empty.')
                        raise SkipBug()

                    if any(not x for x in plist.values()):
                        # skip the bug if at least one package has undefined
                        # keywords (i.e. neither explicitly specified nor
                        # arches CC-ed)
                        log.info('Skipping because of incomplete keywords')
                        comment = ('Resetting sanity check; keywords are '
                                   'not fully specified and arches are not '
                                   'CC-ed.')
                        raise SkipBug()

                    cache_entry = cache['bugs'].get(str(bno), {})
                    assert cache_entry is not None
                    last_check = cache_entry.get('last-check')
                    if last_check is not None:
                        if cache_entry.get('package-list', '') != b.atoms:
                            log.info('Package list changed, will recheck.')
                        elif (cache_entry.get('check-res', None)
                              is not b.sanity_check):
                            log.info('Sanity-check flag changed, '
                                     'will recheck.')
                        elif (datetime.datetime.utcnow()
                              - datetime.datetime.strptime(
                                last_check, '%Y-%m-%dT%H:%M:%S')
                              > datetime.timedelta(
                                seconds=self.args.cache_max_age)):
                            log.info('Cache entry is old, will recheck.')
                        elif (not cache_entry.get('updated')
                              and self.args.update_bugs):
                            log.info('Cache entry from no-update mode, '
                                     'will recheck.')
                        else:
                            log.info('Cache entry is up-to-date, skipping.')
                            continue

                    with git_repo:
                        add_keywords(plist.items(),
                                     b.category == BugCategory.STABLEREQ)
                        check_res, issues = check_dependencies(
                            repo, plist.items())

                        bugs_done += 1

                        cache_entry = cache['bugs'][str(bno)] = {
                            'last-check':
                                datetime.datetime.utcnow().isoformat(
                                    timespec='seconds'),
                            'package-list': b.atoms,
                            'check-res': check_res,
                        }

                        if check_res:
                            # if nothing changed, do nothing
                            if b.sanity_check is True:
                                cache_entry['updated'] = True
                                log.info('Still good')
                                continue

                            # otherwise, update the bug status
                            log.info('All good')
                            # if it was bad before, leave a comment
                            if b.sanity_check is False:
                                comment = ('All sanity-check issues '
                                           'have been resolved')
                        else:
                            issues = sorted(str(x) for x in issues)
                            comment = ('Sanity check failed:\n\n'
                                       + '\n'.join(f'> {x}' for x in issues))
                            log.info('Sanity check failed')
                except (PackageInvalid, PackageNoMatch, KeywordNoMatch) as e:
                    log.error(e)
                    check_res = False
                    comment = f'Unable to check for sanity:\n\n> {e}'
                except GitDirtyWorkTree:
                    log.critical(
                        f'{git_repo.path}: working tree is dirty')
                    raise SystemExit(1)
                except SkipBug:
                    assert check_res is None

                # if we can not check it, and it's not been marked
                # as checked, just skip it;  otherwise, reset the flag
                if check_res is None and b.sanity_check is None:
                    continue

                # for negative results, we verify whether the comment
                # needs to change
                if check_res is False and b.sanity_check is False:
                    assert comment is not None
                    old_comment = bz.get_latest_comment(bno, username)
                    # do not add a second identical comment
                    if (old_comment is not None
                            and comment.strip() == old_comment.strip()):
                        assert cache_entry is not None
                        cache_entry['updated'] = True
                        log.info('Failure reported already')
                        continue

                if self.args.update_bugs:
                    bz.update_status(bno, check_res, comment)
                    if cache_entry is not None:
                        cache_entry['updated'] = True
                    log.info('Bug status updated')
        finally:
            self.write_cache(cache)

        return 0


def main(argv: typing.List[str]) -> int:
    argp = argparse.ArgumentParser()
    argp.add_argument('--version', action='version',
                      version=f'nattka {__version__}',
                      help='print the version and exit')

    logg = argp.add_argument_group('logging')
    logg.add_argument('-q', '--quiet', action='store_true',
                      help='Disable logging')

    bugg = argp.add_argument_group('Bugzilla configuration')
    bugg.add_argument('--api-key',
                      help='Bugzilla API key (read from ~/.bugz_token '
                           'by default')
    bugg.add_argument('--bugzilla-auth',
                      help='Bugzilla HTTP server username:password '
                           '(for HTTP auth protected sites, e.g. bugstest)')
    bugg.add_argument('--bugzilla-endpoint',
                      help='Bugzilla /rest endpoint URL')

    repg = argp.add_argument_group('repository')
    repg.add_argument('--portage-conf', default=None,
                      help='override Portage-style configuration directory')
    repg.add_argument('--repo', default='.',
                      help='repository path (default: .)')

    subp = argp.add_subparsers(title='commands', dest='command')

    bugp = argparse.ArgumentParser(add_help=False)
    bugg = bugp.add_argument_group('bug selection')
    bugg.add_argument('bug', nargs='*', type=int,
                      help='bug(s) to process')

    subp.add_parser('apply',
                    parents=[bugp],
                    help='keyword/stabilize packages according '
                         'to a bug')

    prop = subp.add_parser('process-bugs',
                           parents=[bugp],
                           help='process all open bugs -- apply '
                                'keywords, test, report results')
    prop.add_argument('-u', '--update-bugs', action='store_true',
                      help='commit updates to bugs (running in pretend '
                           'mode by default)')
    limp = prop.add_argument_group('limiting')
    limp.add_argument('--bug-limit', type=int,
                      help='check at most N bugs (only bugs actually '
                           'tested count, default: unlimited')
    limp.add_argument('--time-limit', type=int,
                      help='run checks for at most N seconds '
                           '(default: unlimited')
    cacp = prop.add_argument_group('caching')
    cacp.add_argument('-c', '--cache-file', type=Path,
                      help='path to the file used to cache bug states '
                           '(default: caching disabled)')
    cacp.add_argument('--cache-max-age', type=int, default=12 * 60 * 60,
                      help='max age of cache entries before refreshing '
                           'in seconds (default: 12 hours)')

    args = argp.parse_args(argv)
    if args.command is None:
        argp.error('Command must be specified')

    if args.quiet:
        log.setLevel(logging.CRITICAL)

    cmd = NattkaCommands(args)
    try:
        return getattr(cmd, args.command.replace('-', '_'))()
    except KeyboardInterrupt:
        log.info('Exiting due to ^c')
        return 1
    except SystemExit as e:
        return e.code


def setuptools_main() -> None:
    log.setLevel(logging.INFO)
    sys.exit(main(sys.argv[1:]))


if __name__ == '__main__':
    setuptools_main()
