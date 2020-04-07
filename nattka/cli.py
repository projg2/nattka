# (c) 2020 Michał Górny
# 2-clause BSD license

""" CLI for nattka. """

import argparse
import datetime
import fnmatch
import itertools
import json
import logging
import sys
import typing

from pathlib import Path

from snakeoil.fileutils import AtomicWriteFile
from pkgcore.ebuild.repository import UnconfiguredTree
from pkgcheck.results import Result, VersionResult

from nattka import __version__
from nattka.bugzilla import (NattkaBugzilla, BugInfo, BugCategory,
                             get_combined_buginfo,
                             update_keywords_from_cc)
from nattka.git import GitWorkTree, GitDirtyWorkTree, git_commit
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
            self.bz = NattkaBugzilla(
                self.get_api_key(require_api_key=require_api_key),
                api_url=self.args.bugzilla_endpoint)
        return self.bz

    def find_bugs(self,
                  arch: typing.Optional[typing.List[str]] = [],
                  ) -> typing.Tuple[typing.List[int],
                                    typing.Dict[int, BugInfo]]:
        """
        Find/get bugs according to command-line options

        Return a tuple of (bug numbers, dictionary of bug numbers
        to BugInfo objects).
        """

        bz = self.get_bugzilla()
        kwargs = {}
        if self.args.bug:
            kwargs['bugs'] = self.args.bug
        if getattr(self.args, 'category', []):
            kwargs['category'] = self.args.category
        if getattr(self.args, 'security', False):
            kwargs['security'] = True
        if arch:
            kwargs['cc'] = sorted([f'{x}@gentoo.org' for x in arch])
        bugs = bz.find_bugs(**kwargs)
        bugnos = list(bugs)
        # if user did not specify explicit list of bugs, start with
        # newest
        if not self.args.bug:
            bugnos = list(reversed(sorted(bugnos)))
        if not getattr(self.args, 'no_fetch_dependencies', True):
            bugs = bz.resolve_dependencies(bugs)
        for bno, b in bugs.items():
            bugs[bno] = update_keywords_from_cc(
                b, self.get_repository().known_arches)
        return bugnos, bugs

    def get_repository(self) -> UnconfiguredTree:
        """
        Initialize and return a repo instance.  Caches the result.
        """

        if self.repo is None:
            self.domain, self.repo = find_repository(
                Path(self.args.repo),
                Path(self.args.portage_conf) if self.args.portage_conf
                is not None else None)
            if self.repo is None:
                log.critical(
                    f'Ebuild repository not found in {self.args.repo}')
                log.critical(
                    'Please run from inside the ebuild repository or '
                    'pass correct --repo')
                raise SystemExit(1)

        return self.repo

    def get_git_repository(self
                           ) -> typing.Tuple[UnconfiguredTree, GitWorkTree]:
        """
        Initialize and return a git ebuild repository

        Returns a tuple of (ebuild repository, git repository) objects.
        """

        repo = self.get_repository()
        git_repo = GitWorkTree(repo.location)
        if git_repo.path != Path(repo.location):
            log.critical(
                f'{repo.location} does not seem to be a git repository')
            raise SystemExit(1)
        return repo, git_repo

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

    def get_arch(self) -> typing.List[str]:
        """
        Get list of requested architectures
        """
        repo = self.get_repository()
        if self.args.arch:
            arch = []
            for a in self.args.arch:
                m = fnmatch.filter(repo.known_arches, a)
                if not m:
                    log.critical(
                        f'{a!r} does not match any known arches')
                    raise SystemExit(1)
                arch.extend(m)
        else:
            arch = [self.domain.arch]
            assert arch[0] in repo.known_arches
        return arch

    def apply(self) -> int:
        repo = self.get_repository()
        arch = self.get_arch()

        bugnos, bugs = self.find_bugs(arch=arch)
        for bno in bugnos:
            b = bugs[bno]
            if b.category is None:
                print(f'# bug {bno}: neither stablereq nor keywordreq\n')
                continue

            plist = dict(match_package_list(repo, b.atoms))

            if not plist:
                print(f'# bug {bno}: empty package list\n')
                continue
            if any(not x for x in plist.values()):
                print(f'# bug {bno}: incomplete keywords\n')
                continue
            if (b.sanity_check is not True
                    and not self.args.ignore_sanity_check):
                if b.sanity_check is False:
                    print(f'# bug {bno}: sanity check failed\n')
                else:
                    print(f'# bug {bno}: no sanity check result\n')
                continue
            unresolved_deps = [depno for depno in b.depends
                               if not bugs[depno].resolved]
            if unresolved_deps and not self.args.ignore_dependencies:
                print(f'# bug {bno}: unresolved dependency on '
                      f'{", ".join(str(x) for x in unresolved_deps)}\n')
                continue

            print(f'# bug {bno} ({b.category.name})')
            for p, keywords in list(plist.items()):
                keywords = [k for k in keywords if k in arch]
                if not keywords:
                    del plist[p]
                    continue

                plist[p] = keywords
                kws = ' '.join(f'~{k}' for k in keywords)
                if b.category == BugCategory.STABLEREQ:
                    print(f'={p.cpvstr} {kws}')
                else:
                    print(f'={p.cpvstr} **  # -> {kws}')
            print()
            if not self.args.no_update:
                add_keywords(plist.items(), b.category
                                            == BugCategory.STABLEREQ)

        return 0

    def commit(self) -> int:
        repo, git_repo = self.get_git_repository()
        arch = self.get_arch()

        ret = 0
        bugnos, bugs = self.find_bugs()
        for bno in bugnos:
            b = bugs[bno]
            if b.category is None:
                log.error(f'Bug {bno}: neither stablereq nor keywordreq')
                ret = 1
                continue

            plist = dict(match_package_list(repo, b.atoms))

            if not plist:
                log.error(f'Bug {bno}: empty package list')
                ret = 1
                continue
            if any(not x for x in plist.values()):
                log.error(f'Bug {bno}: incomplete keywords')
                ret = 1
                continue

            log.info(f'Bug {bno} ({b.category.name})')
            for p, keywords in plist.items():
                keywords = [k for k in keywords if k in arch]
                if not keywords:
                    continue

                ebuild_path = Path(p.path).relative_to(repo.location)
                pfx = f'{p.category}/{p.package}'
                act = ('Stabilize' if b.category == BugCategory.STABLEREQ
                       else 'Keyword')
                kws = ' '.join(keywords)
                msg = f'{pfx}: {act} {p.fullver} {kws}, #{bno}'
                print(git_commit(git_repo.path, msg, [str(ebuild_path)]))

        return ret

    @staticmethod
    def format_results(issues: typing.Iterable[Result]
                       ) -> typing.Iterator[str]:
        for r in issues:
            assert isinstance(r, VersionResult)
        for key, values in itertools.groupby(
                issues,
                key=lambda r: (r.category, r.package, r.version)):
            yield f'> {key[0]}/{key[1]}-{key[2]}:'
            for r in sorted(values):
                yield f'>   {r.desc}'

    def process_bugs(self) -> int:
        repo, git_repo = self.get_git_repository()

        if not self.args.update_bugs:
            log.warning(f'Running in pretend mode.')
            log.warning(f'(pass --update-bugs to enable bug updates)')

        cache = self.get_cache()
        cache.setdefault('bugs', {})

        start_time = datetime.datetime.utcnow()
        log.info(f'NATTkA starting at {start_time}')
        end_time = None
        if self.args.time_limit is not None:
            end_time = (start_time
                        + datetime.timedelta(seconds=self.args.time_limit))
            log.info(f'... will process until {end_time}')

        bz = self.get_bugzilla(require_api_key=self.args.update_bugs)
        username = bz.whoami()
        bugnos, bugs = self.find_bugs()
        log.info(f'Found {len(bugnos)} bugs')
        bugs_done = 0

        try:
            for bno in bugnos:
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
                # processing bug without its dependencies may result
                # in issuing false positives
                if any(dep not in bugs for dep in b.depends):
                    log.warning(f'Bug {bno}: dependencies not fetched, '
                                f'skipping')
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
                        if bugs_done > 0 and bugs_done % 10 == 0:
                            log.info(f'Tested {bugs_done} bugs so far')

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
                            issues = list(self.format_results(issues))
                            comment = ('Sanity check failed:\n\n'
                                       + '\n'.join(issues))
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
                        if cache_entry is not None:
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
            end_time = datetime.datetime.utcnow()
            log.info(f'NATTkA exiting at {end_time}')
            log.info(f'Total time elapsed: {end_time - start_time}')

        return 0


def main(argv: typing.List[str]) -> int:
    argp = argparse.ArgumentParser()
    argp.add_argument('--version', action='version',
                      version=f'nattka {__version__}',
                      help='print the version and exit')

    logg = argp.add_argument_group('logging')
    logg = logg.add_mutually_exclusive_group()
    logg.add_argument('-q', '--quiet', action='store_true',
                      help='disable logging')
    logg.add_argument('--log-file',
                      help='log to specified file')

    bugg = argp.add_argument_group('Bugzilla configuration')
    bugg.add_argument('--api-key',
                      help='Bugzilla API key (read from ~/.bugz_token '
                           'by default')
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
    bugg.add_argument('--keywordreq', dest='category',
                      action='append_const', const=BugCategory.KEYWORDREQ,
                      help='filter results to KEYWORDREQs')
    bugg.add_argument('--stablereq', dest='category',
                      action='append_const', const=BugCategory.STABLEREQ,
                      help='filter results to STABLEREQs')
    bugg.add_argument('--security', action='store_true',
                      help='process security bugs only')
    bugg.add_argument('--no-fetch-dependencies', action='store_true',
                      help='disable fetching missing dependency bugs')
    bugg.add_argument('bug', nargs='*', type=int,
                      help='bug(s) to process (defaults to all open '
                           'keywording and stabilization bugs if not '
                           'specified')

    appp = subp.add_parser('apply',
                           parents=[bugp],
                           help='keyword/stabilize packages according '
                                'to a bug and print their list')
    appp.add_argument('-a', '--arch', action='append',
                      help='process specified arch (default: current '
                           'according to pkgcore config, accepts '
                           'fnmatch-style wildcards)')
    appp.add_argument('--ignore-dependencies', action='store_true',
                      help='do not skip bugs that have unresolved '
                           'dependencies')
    appp.add_argument('--ignore-sanity-check', action='store_true',
                      help='do not skip bugs that are not marked '
                           'as passing sanity-check')
    appp.add_argument('-n', '--no-update', action='store_true',
                      help='do not update KEYWORDS in packages, only '
                           'output the list')

    comp = subp.add_parser('commit',
                           help='commit changes in ebuilds specified '
                                'in bugs')
    comp.add_argument('bug', nargs='+', type=int,
                      help='bug(s) to process')
    comp.add_argument('-a', '--arch', action='append',
                      help='process specified arch (default: current '
                           'according to pkgcore config, accepts '
                           'fnmatch-style wildcards)')

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

    log.setLevel(logging.INFO)
    if args.quiet:
        log.setLevel(logging.CRITICAL)

    if args.log_file:
        ch = logging.StreamHandler()
        ch.setLevel(logging.CRITICAL)
        log.addHandler(ch)
        fh = logging.FileHandler(args.log_file)
        ff = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        fh.setFormatter(ff)
        log.propagate = False
        log.addHandler(fh)

    cmd = NattkaCommands(args)
    try:
        return getattr(cmd, args.command.replace('-', '_'))()
    except KeyboardInterrupt:
        log.info('Exiting due to ^c')
        return 1
    except SystemExit as e:
        return e.code


def setuptools_main() -> None:
    sys.exit(main(sys.argv[1:]))


if __name__ == '__main__':
    setuptools_main()
