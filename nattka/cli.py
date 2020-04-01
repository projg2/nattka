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

    def get_api_key(self) -> str:
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
        log.error('Please pass --api-key or put it in ~/.bugz_token')
        raise SystemExit(1)

    def get_bugzilla(self) -> NattkaBugzilla:
        """
        Initialize and return a bugzilla instance.  Caches the result.
        """

        if self.bz is None:
            # TODO: restore type checking once we get rid of auth
            kwargs: typing.Dict[str, typing.Any] = {}
            if self.args.bugzilla_auth is not None:
                kwargs['auth'] = tuple(self.args.bugzilla_auth.split(':', 1))
            if self.args.bugzilla_endpoint is not None:
                kwargs['api_url'] = self.args.bugzilla_endpoint
            self.bz = NattkaBugzilla(self.get_api_key(), **kwargs)
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
            log.error(f'{repo.location} does not seem to be a git repository')
            raise SystemExit(1)

        cache = self.get_cache()
        cache.setdefault('bugs', {})

        bz = self.get_bugzilla()
        username = bz.whoami()
        bugs = self.find_bugs()
        log.info(f'Found {len(bugs)} bugs')

        try:
            # start with the newest bugs
            for bno in reversed(sorted(bugs)):
                b = get_combined_buginfo(bugs, bno)
                if b.category is None:
                    log.info(f'Bug {bno}: neither stablereq nor keywordreq')
                    continue

                log.info(f'Bug {bno} ({b.category.name})')

                try:
                    comment: typing.Optional[str] = None
                    check_res: typing.Optional[bool] = None

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
                    last_check = cache_entry.get('last-check')
                    if last_check is not None:
                        if cache_entry.get('package-list', '') != b.atoms:
                            log.info('Package list changed, will recheck.')
                        elif (cache_entry.get('check-res', None)
                              is not b.sanity_check):
                            log.info('Sanity-check flag changed, '
                                     'will recheck.')
                        elif (datetime.datetime.utcnow()
                              - datetime.datetime.fromisoformat(last_check)
                              > datetime.timedelta(
                                seconds=self.args.cache_max_age)):
                            log.info('Cache entry is old, will recheck.')
                        else:
                            log.info('Cache entry is up-to-date, skipping.')
                            continue

                    with git_repo:
                        add_keywords(plist.items(),
                                     b.category == BugCategory.STABLEREQ)
                        check_res, issues = check_dependencies(
                            repo, plist.items())

                        # do not update cache when not updating bugzilla
                        if not self.args.no_update:
                            cache['bugs'][str(bno)] = {
                                'last-check':
                                    datetime.datetime.utcnow().isoformat(),
                                'package-list': b.atoms,
                                'check-res': check_res,
                            }

                        if check_res:
                            # if nothing changed, do nothing
                            if b.sanity_check is True:
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
                    log.error(f'{git_repo.path}: working tree is dirty')
                    raise SystemExit(1)
                except SkipBug:
                    pass
                except Exception as e:
                    log.error(f'TODO: handle exception {e.__class__} {e}')
                    continue

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
                        log.info('Failure reported already')
                        continue

                if not self.args.no_update:
                    bz.update_status(bno, check_res, comment)
                    log.info('Bug status updated')
        finally:
            self.write_cache(cache)

        return 0


def main(argv: typing.List[str]) -> int:
    argp = argparse.ArgumentParser()
    argp.add_argument('--api-key',
                      help='Bugzilla API key (read from ~/.bugz_token '
                           'by default')
    argp.add_argument('--bugzilla-auth',
                      help='Bugzilla HTTP server username:password '
                           '(for HTTP auth protected sites, e.g. bugstest)')
    argp.add_argument('--bugzilla-endpoint',
                      help='Bugzilla /rest endpoint URL')
    argp.add_argument('--portage-conf', default=None,
                      help='Override Portage-style configuration directory')
    argp.add_argument('--repo', default='.',
                      help='Repository path (default: .)')
    subp = argp.add_subparsers(title='commands', dest='command')

    appp = subp.add_parser('apply',
                           help='Keyword/stabilize packages according '
                                'to a bug')
    appp.add_argument('bug', nargs='+', type=int,
                      help='Bug(s) to process')

    prop = subp.add_parser('process-bugs',
                           help='Process all open bugs -- apply '
                                'keywords, test, report results')
    prop.add_argument('-c', '--cache-file', type=Path,
                      help='Path to the file used to cache bug states '
                           '(default: caching disabled)')
    prop.add_argument('--cache-max-age', type=int, default=12 * 60 * 60,
                      help='Max age of cache entries before refreshing '
                           'in seconds (default: 12 hours)')
    prop.add_argument('-n', '--no-update', action='store_true',
                      help='Do not commit updates to the bugs, only '
                           'check them and report what would be done')
    prop.add_argument('bug', nargs='*', type=int,
                      help='Bug(s) to process (default: find all)')

    args = argp.parse_args(argv)
    if args.command is None:
        argp.error('Command must be specified')

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
