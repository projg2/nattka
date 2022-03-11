# (c) 2020-2021 Michał Górny
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
from pkgcore.ebuild.atom import atom
from pkgcore.ebuild.repository import UnconfiguredTree

from nattka import __version__
from nattka.bugzilla import (NattkaBugzilla, BugInfo, BugCategory,
                             arches_from_cc, split_dependent_bugs)
from nattka.git import (GitCommitNoChanges, GitDirtyWorkTree,
                        GitWorkTree, git_commit)
from nattka.package import (find_repository, match_package_list,
                            add_keywords, check_dependencies,
                            PackageMatchException, KeywordNotSpecified,
                            PackageListEmpty, PackageListDoneAlready,
                            KeywordNoneLeft, is_allarches, is_masked,
                            package_list_to_json, merge_package_list,
                            expand_package_list, ExpandImpossible,
                            format_results, filter_prefix_keywords,
                            PackageKeywordsDict, get_suggested_keywords,
                            load_profiles, MaskReason,
                            can_allarches_for_keywords)

try:
    from nattka.depgraph import (get_ordered_nodes,
                                 get_depgraph_for_packages)
    have_nattka_depgraph = True
except ImportError:
    have_nattka_depgraph = False


BUGZILLA_MAX_COMMENT_LEN = 16384

log = logging.getLogger('nattka')


class DependentBugError(Exception):
    pass


class PackageMasked(PackageMatchException):
    pass


class NoChanges(Exception):
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
        else:
            kwargs.update({
                'category': [BugCategory.KEYWORDREQ,
                             BugCategory.STABLEREQ],
                'skip_tags': ['nattka:skip'],
                'unresolved': True,
            })
        if getattr(self.args, 'category', []):
            kwargs['category'] = self.args.category
        if arch:
            kwargs['cc'] = sorted([f'{x}@gentoo.org' for x in arch])
        bugs = bz.find_bugs(**kwargs)

        # hack: Bugzilla seems to suffer from a race condition that can
        # result in closed bugs being returned when a bug is closed
        # during the search (as in, actually returned as closed)
        if not self.args.bug:
            for bugno, bug in list(bugs.items()):
                if bug.resolved:
                    del bugs[bugno]

        # manually filter security bugs due to complex condition
        if getattr(self.args, 'security', False):
            for bugno, bug in list(bugs.items()):
                if not bug.security and 'SECURITY' not in bug.keywords:
                    del bugs[bugno]

        bugnos = list(bugs)
        # if user did not specify explicit list of bugs, start with
        # newest
        if not self.args.bug:
            bugnos = list(reversed(sorted(bugnos)))
        if not getattr(self.args, 'no_fetch_dependencies', True):
            bugs = bz.resolve_dependencies(bugs)
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
        if not git_repo.path.samefile(repo.location):
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

        if not have_nattka_depgraph:
            log.warning(
                'Unable to import nattka.depgraph, dependency sorting '
                'will not be available')
            log.warning('(nattka.depgraph requires networkx)')

        ret = 0
        bugnos, bugs = self.find_bugs(arch=arch)
        for bno in bugnos:
            b = bugs[bno]
            if b.category is None:
                print(f'# bug {bno}: neither stablereq nor keywordreq\n')
                ret = 1
                continue

            try:
                plist = dict(match_package_list(
                    repo, b, only_new=True, filter_arch=arch,
                    permit_allarches=not self.args.ignore_allarches))
            except PackageMatchException as e:
                print(f'# bug {bno}: {e}\n')
                ret = 1
                continue

            if (b.sanity_check is not True
                    and not self.args.ignore_sanity_check):
                if b.sanity_check is False:
                    print(f'# bug {bno}: sanity check failed\n')
                else:
                    print(f'# bug {bno}: no sanity check result\n')
                ret = 1
                continue

            all_keywords = frozenset(
                itertools.chain.from_iterable(plist.values()))
            unresolved_deps = []
            for depno in b.depends:
                depb = bugs[depno]
                if depb.resolved:
                    continue
                if depb.category == b.category:
                    try:
                        for depp, depkw in match_package_list(
                                repo, depb, only_new=True,
                                filter_arch=all_keywords):
                            pass
                    except PackageListEmpty:
                        # ignore dependent bugs with empty package list
                        # or mismatched keywords
                        # (assuming the bug passed sanity-check anyway)
                        continue
                    except PackageMatchException:
                        pass
                unresolved_deps.append(depno)

            if unresolved_deps and not self.args.ignore_dependencies:
                print(f'# bug {bno}: unresolved dependency on '
                      f'{", ".join(str(x) for x in unresolved_deps)}\n')
                ret = 1
                continue

            if have_nattka_depgraph:
                graph = get_depgraph_for_packages(plist)
                ordered_nodes = list(get_ordered_nodes(graph))
                order = sorted(plist,
                               key=lambda x: (ordered_nodes.index(x.key),
                                              x.fullver))
            else:
                order = list(plist)

            allarches = (not self.args.ignore_allarches
                         and 'ALLARCHES' in b.keywords)
            print(f'# bug {bno} ({b.category.name})'
                  f'{" ALLARCHES" if allarches else ""}')
            for p in order:
                kws = ' '.join(f'~{k}' for k in plist[p])
                if b.category == BugCategory.STABLEREQ:
                    print(f'={p.cpvstr} {kws}')
                else:
                    print(f'={p.cpvstr} **  # -> {kws}')
            print()
            if not self.args.no_update:
                add_keywords(plist.items(), b.category
                                            == BugCategory.STABLEREQ)

        return ret

    def commit(self) -> int:
        repo, git_repo = self.get_git_repository()
        arch = self.get_arch()

        if not have_nattka_depgraph:
            log.warning(
                'Unable to import nattka.depgraph, dependency sorting '
                'will not be available')
            log.warning('(nattka.depgraph requires networkx)')

        ret = 0
        bugnos, bugs = self.find_bugs()
        for bno in bugnos:
            b = bugs[bno]
            if b.category is None:
                log.error(f'Bug {bno}: neither stablereq nor keywordreq')
                ret = 1
                continue

            try:
                plist = dict(match_package_list(
                    repo, b, filter_arch=arch,
                    permit_allarches=not self.args.ignore_allarches))
            except PackageMatchException as e:
                log.error(f'Bug {bno}: {e}')
                ret = 1
                continue

            if have_nattka_depgraph:
                graph = get_depgraph_for_packages(plist)
                ordered_nodes = list(get_ordered_nodes(graph))
                order = sorted(plist,
                               key=lambda x: (ordered_nodes.index(x.key),
                                              x.fullver))
            else:
                order = list(plist)

            allarches = (not self.args.ignore_allarches
                         and 'ALLARCHES' in b.keywords)
            log.info(f'Bug {bno} ({b.category.name})'
                     f'{" ALLARCHES" if allarches else ""}')
            for p in order:
                keywords = [k for k in plist[p] if k in arch]
                if not keywords:
                    continue

                ebuild_path = Path(p.path).relative_to(repo.location)
                pfx = f'{p.category}/{p.package}'
                act = ('Stabilize' if b.category == BugCategory.STABLEREQ
                       else 'Keyword')
                if allarches:
                    kws = 'ALLARCHES'
                else:
                    kws = ' '.join(keywords)
                msg = f'{pfx}: {act} {p.fullver} {kws}, #{bno}'
                try:
                    print(git_commit(git_repo.path,
                                     msg,
                                     [str(ebuild_path)]))
                except GitCommitNoChanges:
                    pass

        return ret

    def make_package_list(self) -> int:
        repo, git_repo = self.get_git_repository()

        with git_repo:
            start_time = datetime.datetime.utcnow()
            packages = self.args.package
            if self.args.arch is None:
                initial_arches = '*'
            else:
                initial_arches = ' '.join(self.args.arch)
            if self.args.stabilization:
                bug_cat = BugCategory.STABLEREQ
                pkg_attr = 'cpvstr'
            else:
                bug_cat = BugCategory.KEYWORDREQ
                pkg_attr = 'key'

            b = BugInfo(bug_cat, f'{packages[0]} {initial_arches}\n')
            plist = dict(match_package_list(repo, b, only_new=True))
            assert len(plist) == 1
            cc_arches = sorted(
                [f'{x}@gentoo.org' for x
                 in set(itertools.chain.from_iterable(plist.values()))
                 if '-' not in x])

            it = 1
            # prepare the initial set
            b = BugInfo(bug_cat, '\n'.join(packages), cc=cc_arches)
            new_plist = dict(match_package_list(repo, b, only_new=True))
            add_keywords(plist.items(),
                         b.category == BugCategory.STABLEREQ)

            while True:
                log.info(f'Iteration {it}: running pkgcheck ...')
                plist = new_plist
                check_res, issues = check_dependencies(
                    repo, plist.items())

                # all good? we're done!
                if check_res:
                    break

                new_packages = set()
                for i in issues:
                    eapi = repo[(i.category, i.package, i.version)].eapi
                    for d in i.deps:
                        # TODO: handle USE-deps meaningfully
                        # TODO: handle <-deps
                        r = atom(d, eapi=eapi).no_usedeps
                        for m in reversed(sorted(repo.itermatch(r))):
                            if b.category == BugCategory.STABLEREQ:
                                # skip unkeyworded ebuilds
                                if not m.keywords:
                                    continue
                            new_packages.add(getattr(m, pkg_attr))
                            break
                        else:
                            log.error(f'No match for dependency: {d}')
                            return 1

                assert new_packages
                log.info(
                    f'New packages: {" ".join(sorted(new_packages))}')

                # apply on *new* packages
                b = BugInfo(bug_cat, '\n'.join(new_packages), cc=cc_arches)
                new_plist = dict(match_package_list(repo, b, only_new=True))
                for p in list(new_packages):
                    if not any(getattr(x, pkg_attr) == p for x in new_plist):
                        log.info(f'Package {p} seems to be a red herring '
                                 f'(already keyworded everywhere)')
                        new_packages.remove(p)
                add_keywords(new_plist.items(),
                             b.category == BugCategory.STABLEREQ)

                # but test on *old*
                log.info(f'Iteration {it}: verifying ...')
                check_res, issues = check_dependencies(
                    repo, plist.items())
                if not check_res:
                    log.error('Attempt to satisfy dependencies failed:')
                    log.error('\n'.join(format_results(issues)))
                    log.error('Please correct the package list and retry.')
                    break

                for x in sorted(new_packages):
                    # TODO: handle it gracefully
                    assert x not in packages
                    packages.append(x)

                it += 1

        end_time = datetime.datetime.utcnow()
        log.info(f'Time elapsed: {end_time - start_time}')
        log.info(f'Target CC: {" ".join(cc_arches)}')

        if self.args.stabilization:
            log.warning('The package list contains newest versions visible.')
            log.warning('Please adjust the package list to desired versions.')

        log.info('Package list follows:')
        print(f'{packages[0]} {initial_arches}')
        print('\n'.join(f'{x} ^' for x in packages[1:]))

        return 0

    def resolve(self) -> int:
        repo = self.get_repository()
        arch = self.get_arch()
        bz = self.get_bugzilla(require_api_key=not self.args.pretend)

        ret = 0
        bugnos, bugs = self.find_bugs()
        for bno in bugnos:
            b = bugs[bno]
            if b.category is None:
                log.error(f'Bug {bno}: neither stablereq nor keywordreq')
                ret = 1
                continue

            current_arches = set(arches_from_cc(b.cc, repo.known_arches))
            allarches = (not self.args.ignore_allarches
                         and 'ALLARCHES' in b.keywords)
            if allarches:
                to_remove = current_arches
            else:
                to_remove = current_arches.intersection(arch)
            if not to_remove:
                log.warning(f'Bug {bno}: no specified arches CC-ed, '
                            f'found: {" ".join(sorted(current_arches))}')
                continue

            all_done = (current_arches == to_remove)
            to_close = (all_done and not b.security and not b.resolved
                        and not self.args.no_resolve)

            log.info(f'Bug {bno} ({b.category.name})')
            if self.args.pretend:
                log.info(f'pretend: would un-CC '
                         f'{" ".join(sorted(to_remove))}'
                         f'{" (ALLARCHES)" if allarches else ""}')
                if to_close:
                    log.info('pretend: would resolve the bug')
            else:
                comment = (f'{" ".join(sorted(to_remove))} '
                           f'{"(ALLARCHES) " if allarches else ""}'
                           f'done')
                if all_done:
                    comment += '\n\nall arches done'
                bz.resolve_bug(
                    bno,
                    sorted([f'{x}@gentoo.org' for x in to_remove]),
                    comment,
                    to_close)
                log.info('Bug updated')

        return ret

    def sanity_check(self) -> int:
        repo, git_repo = self.get_git_repository()

        if not self.args.update_bugs:
            log.warning('Running in pretend mode.')
            log.warning('(pass --update-bugs to enable bug updates)')

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
        bugnos, bugs = self.find_bugs()
        log.info(f'Found {len(bugnos)} bugs')
        bugs_done = 0
        profiles = load_profiles(repo)

        try:
            for bno in bugnos:
                if self.args.bug_limit and bugs_done >= self.args.bug_limit:
                    log.info(f'Reached limit of {self.args.bug_limit} bugs')
                    break
                if (end_time is not None
                        and datetime.datetime.utcnow() > end_time):
                    log.info('Reached time limit')
                    break

                b = bugs[bno]
                # Bugzilla is prone to race conditions between fetching bug
                # data and updating bugs, so ignore bugs that have been updated
                # recently.
                if ((start_time - b.last_change_time).total_seconds() < 60
                        and self.args.update_bugs):
                    log.info(f'Bug {bno}: skipping due to recent change')
                    continue
                if b.category is None:
                    log.info(f'Bug {bno}: neither stablereq nor keywordreq')
                    continue
                kw_deps, reg_deps = split_dependent_bugs(bugs, bno)
                # processing bug without its dependencies may result
                # in issuing false positives
                if any(dep not in bugs for dep in reg_deps):
                    log.warning(f'Bug {bno}: dependencies not fetched, '
                                f'skipping')
                    continue

                log.info(f'Bug {bno} ({b.category.name})')

                plist: PackageKeywordsDict = {}
                comment: typing.Optional[str] = None
                check_res: typing.Optional[bool] = None
                cache_entry: typing.Optional[dict] = None
                cc_arches: typing.List[str] = []
                cc_maintainers: typing.List[str] = []
                allarches_chg = False
                expanded_plist: typing.Optional[str] = None
                need_security_kw = False

                try:
                    arches_cced = bool(
                        arches_from_cc(b.cc, repo.known_arches))
                    try:
                        for p, kw in match_package_list(repo, b,
                                                        only_new=True):
                            masked, mask_kws = is_masked(repo, p, kw,
                                                         profiles)
                            if masked == MaskReason.REPOSITORY_MASK:
                                raise PackageMasked(
                                    f'package masked: {p.cpvstr}')
                            elif masked == MaskReason.PROFILE_MASK:
                                raise PackageMasked(
                                    f'package masked: {p.cpvstr}, '
                                    f'in all profiles for arch: '
                                    f'{" ".join(mask_kws)}')
                            elif masked == MaskReason.KEYWORD_MASK:
                                raise PackageMasked(
                                    f'package masked: {p.cpvstr}, '
                                    f'by keywords: {" ".join(mask_kws)}')
                            plist[p] = kw
                    except (KeywordNotSpecified, KeywordNoneLeft):
                        assert not arches_cced
                        assert plist
                        # this is raised after iterating all entries,
                        # so plist is usable already
                        if 'CC-ARCHES' not in b.keywords:
                            raise
                        all_keywords = set()
                        for p, kw in plist.items():
                            fkw = frozenset(kw)
                            if not fkw:
                                fkw = get_suggested_keywords(
                                    repo, p,
                                    b.category == BugCategory.STABLEREQ)
                            all_keywords.add(fkw)
                            # we can CC arches iff all packages have
                            # consistent (potential) keywords
                            if len(all_keywords) > 1 or not fkw:
                                raise
                            plist[p] = list(fkw)

                    check_packages = dict(plist)
                    for kw_dep in kw_deps:
                        try:
                            merge_package_list(
                                plist,
                                match_package_list(
                                    repo, bugs[kw_dep], only_new=True))
                        except (KeywordNotSpecified, KeywordNoneLeft):
                            raise DependentBugError(
                                f'dependent bug #{kw_dep} is missing keywords')
                        except PackageListEmpty:
                            # ignore the dependent bug
                            continue
                        except PackageMatchException:
                            raise DependentBugError(
                                f'dependent bug #{kw_dep} has errors')

                    # check if we have arches to CC
                    if 'CC-ARCHES' in b.keywords and not arches_cced:
                        if b.assigned_to != 'bug-wranglers@gentoo.org':
                            cc_arches = sorted(
                                [f'{x}@gentoo.org' for x
                                 in set(filter_prefix_keywords(
                                     itertools.chain.from_iterable(
                                         check_packages.values())))])
                        cc_maintainers = sorted(
                            set(m.email for m in itertools.chain.from_iterable(
                                pkg.maintainers for pkg
                                in check_packages.keys()))
                            .difference(b.cc).difference([b.assigned_to]))

                    # check if we have ALLARCHES to toggle
                    allarches = (b.category == BugCategory.STABLEREQ
                                 and all(is_allarches(x) for x in plist)
                                 and can_allarches_for_keywords(
                                     repo, check_packages.items()))
                    allarches_chg = (allarches != ('ALLARCHES' in b.keywords))

                    # check if we should add SECURITY keyword
                    if not b.security and 'SECURITY' not in b.keywords:
                        # SECURITY keyword doesn't apply to bugs in security
                        # product
                        for blocked_no in b.blocks:
                            try:
                                blocked_bug = bugs[blocked_no]
                            except KeyError:
                                blocked_bug = (
                                    self.get_bugzilla()
                                    .find_bugs(bugs=[blocked_no])[blocked_no])
                            if blocked_bug.security:
                                need_security_kw = True
                                break

                    # check if keywords need expanding
                    if (('*' in b.atoms or '^' in b.atoms)
                            and (arches_cced or cc_arches)):
                        try:
                            expanded_plist = expand_package_list(
                                repo, b, cc_arches or b.cc)
                        except ExpandImpossible:
                            pass

                    plist_json = package_list_to_json(plist.items())
                    cache_entry = cache['bugs'].get(str(bno), {})
                    assert cache_entry is not None
                    last_check = cache_entry.get('last-check')
                    if last_check is not None:
                        if cache_entry.get('package-list', '') != plist_json:
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
                            log.info('Cache entry is up-to-date.')
                            raise NoChanges()

                    with git_repo:
                        add_keywords(plist.items(),
                                     b.category == BugCategory.STABLEREQ)
                        check_res, issues = check_dependencies(
                            repo, check_packages.items())

                        bugs_done += 1
                        if bugs_done > 0 and bugs_done % 10 == 0:
                            log.info(f'Tested {bugs_done} bugs so far')

                        cache_entry = cache['bugs'][str(bno)] = {
                            'last-check':
                                datetime.datetime.utcnow().isoformat(
                                    timespec='seconds'),
                            'package-list': plist_json,
                            'check-res': check_res,
                        }

                        if check_res:
                            # if nothing changed, do nothing
                            if b.sanity_check is True:
                                cache_entry['updated'] = True
                                log.info('Still good')
                                raise NoChanges()

                            # otherwise, update the bug status
                            log.info('All good')
                            # if it was bad before, leave a comment
                            if b.sanity_check is False:
                                comment = ('All sanity-check issues '
                                           'have been resolved')
                        else:
                            issues = list(format_results(issues))
                            comment = ('Sanity check failed:\n\n'
                                       + '\n'.join(issues))
                            log.info('Sanity check failed')
                except KeywordNoneLeft:
                    # do not update bug status, it's probably done
                    log.info('Skipping, no CC and probably no work to do')
                    continue
                except KeywordNotSpecified as e:
                    e_packages = '\n'.join(f'- {x}' for x in e.pkgs)
                    log.info('Skipping because of incomplete keywords')
                    comment = (f'Keywords are not fully specified and '
                               f'arches are not CC-ed for the following '
                               f'packages:\n\n{e_packages}')
                    assert check_res is None
                except PackageListDoneAlready:
                    # do not update bug status if done already
                    log.info('Skipping, work done already')
                    continue
                except PackageListEmpty:
                    log.info('Skipping because of empty package list')
                    comment = ('Resetting sanity check; package list '
                               'is empty or all packages are done.')
                    assert check_res is None
                except (PackageMatchException, DependentBugError) as e:
                    log.error(e)
                    check_res = False
                    comment = f'Unable to check for sanity:\n\n> {e}'
                except NoChanges:
                    # check if we need to add SECURITY keyword
                    if not need_security_kw:
                        # if it's not positive, don't do extra work
                        if b.sanity_check is not True:
                            continue
                        # check if there's anything related to do
                        if not cc_arches and expanded_plist is None:
                            continue
                    check_res = True
                except GitDirtyWorkTree:
                    log.critical(
                        f'{git_repo.path}: working tree is dirty')
                    raise SystemExit(1)

                # if we can not check it, and it's not been marked
                # as checked, just skip it;  otherwise, reset the flag
                if check_res is None and b.sanity_check is None:
                    continue

                # truncate comment if necessary
                if (comment is not None
                        and len(comment) >= BUGZILLA_MAX_COMMENT_LEN):
                    comment = (
                        comment[:BUGZILLA_MAX_COMMENT_LEN - 4] + '...\n')

                # for negative results, we verify whether the comment
                # needs to change
                if check_res is False and b.sanity_check is False:
                    assert comment is not None
                    old_comment = bz.get_latest_comment(bno)
                    # do not add a second identical comment
                    if (old_comment is not None
                            and comment.strip() == old_comment.strip()):
                        if cache_entry is not None:
                            cache_entry['updated'] = True
                        log.info('Failure reported already')
                        continue

                if check_res is not True:
                    # CC arches and change ALLARCHES only after
                    # successful check
                    cc_arches = []
                    allarches_chg = False
                    expanded_plist = None
                elif b.sanity_check is True:
                    # change ALLARCHES only on state changes
                    allarches_chg = False

                if cc_arches:
                    log.info(f'CC arches: {" ".join(cc_arches)}')
                if cc_maintainers:
                    log.info(f'CC maintainers: {" ".join(cc_maintainers)}')
                if allarches_chg:
                    log.info(f'{"Adding" if allarches else "Removing"} '
                             f'ALLARCHES')
                if need_security_kw:
                    log.info('Adding SECURITY keyword')
                if expanded_plist:
                    log.info('Expanding package list')
                    if not self.args.update_bugs:
                        log.info(f'New package list: {expanded_plist}')
                if self.args.update_bugs:
                    kwargs = {}
                    if cc_arches:
                        kwargs['cc_add'] = cc_arches + cc_maintainers
                    keywords_add = []
                    if allarches_chg:
                        if allarches:
                            keywords_add.append('ALLARCHES')
                        else:
                            kwargs['keywords_remove'] = ['ALLARCHES']
                    if need_security_kw:
                        keywords_add.append('SECURITY')
                    if keywords_add:
                        kwargs['keywords_add'] = keywords_add
                    if expanded_plist:
                        kwargs['new_package_list'] = [expanded_plist]
                    bz.update_status(bno, check_res, comment,
                                     **kwargs)
                    if cache_entry is not None:
                        cache_entry['updated'] = True
                    log.info('Bug status updated')
                else:
                    log.info(f'New comment: {comment}')
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
    appp.add_argument('--ignore-allarches', action='store_true',
                      help='do not perform ALLARCHES stabilization '
                           'even if the bug is keyworded for it')
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
    comp.add_argument('--ignore-allarches', action='store_true',
                      help='do not perform ALLARCHES stabilization '
                           'even if the bug is keyworded for it')

    mkpp = subp.add_parser('make-package-list',
                           help='Try to create a complete package list '
                                'for keywording (with dependencies)')
    mkpp.add_argument('-a', '--arch', action='append',
                      help='arch to keyword the first package for '
                           '(default: "*")')
    mkpp.add_argument('-s', '--stabilization', action='store_true',
                      help='prepare a package list for stabilization')
    mkpp.add_argument('package', nargs='+',
                      help='packages to keyword, first being the base '
                           'package (to which -a applies), '
                           'the remaining its dependencies (using "^")')

    resp = subp.add_parser('resolve',
                           help='unCC arches from specified bugs '
                                'and resolve them if appropriate')
    resp.add_argument('bug', nargs='+', type=int,
                      help='bug(s) to process')
    resp.add_argument('-a', '--arch', action='append',
                      help='process specified arch (default: current '
                           'according to pkgcore config, accepts '
                           'fnmatch-style wildcards)')
    resp.add_argument('--ignore-allarches', action='store_true',
                      help='do not perform ALLARCHES stabilization '
                           'even if the bug is keyworded for it')
    resp.add_argument('--no-resolve', action='store_true',
                      help='do not resolve bug even if it should '
                           'be closed per the usual rules')
    resp.add_argument('-p', '--pretend', action='store_true',
                      help='do not update bugs, just print what would '
                           'be done')

    prop = subp.add_parser('sanity-check',
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
