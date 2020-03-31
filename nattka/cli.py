""" CLI for nattka. """

import argparse
import logging
import sys

from pathlib import Path

from pkgcore.util.parserestrict import ParseError

from nattka.bugzilla import (NattkaBugzilla, BugCategory,
                             get_combined_buginfo,
                             fill_keywords_from_cc)
from nattka.git import GitWorkTree, GitDirtyWorkTree
from nattka.package import (find_repository, match_package_list,
                            add_keywords, check_dependencies)


log = logging.getLogger('nattka')


class NattkaCommands(object):
    def __init__(self, args):
        self.args = args

    def get_api_key(self):
        if self.args.api_key is not None:
            return self.args.api_key
        with open(Path.home() / '.bugz_token', 'r') as f:
            return f.read().strip()
        log.error('Please pass --api-key or put it in ~/.bugz_token')
        raise SystemExit(1)

    def get_bugzilla(self):
        kwargs = {}
        if self.args.bugzilla_auth is not None:
            kwargs['auth'] = tuple(self.args.bugzilla_auth.split(':', 1))
        if self.args.bugzilla_endpoint is not None:
            kwargs['api_url'] = self.args.bugzilla_endpoint

        return NattkaBugzilla(self.get_api_key(), **kwargs)

    def apply(self):
        repo = find_repository(self.args.repo, self.args.portage_conf)

        bz = self.get_bugzilla()
        for bugno, b in bz.fetch_package_list(self.args.bug).items():
            b = fill_keywords_from_cc(b, repo.known_arches)
            log.info('Bug {} ({})'.format(bugno, b.category.name))
            plist = dict(match_package_list(repo, b.atoms))
            for p, keywords in plist.items():
                log.info('Package {}: {}'.format(p.cpvstr, plist[p]))
            add_keywords(plist.items(), b.category == BugCategory.STABLEREQ)

        return 0

    def process_bugs(self):
        repo = find_repository(self.args.repo, self.args.portage_conf)
        git_repo = GitWorkTree(repo.location)
        if git_repo.path != Path(repo.location):
            log.error('{} does not seem to be a git repository'
                      .format(repo.location))
            raise SystemExit(1)

        bz = self.get_bugzilla()
        username = bz.whoami()
        bugs = bz.find_bugs(None)
        for bno, b in bugs.items():
            bugs[bno] = fill_keywords_from_cc(b, repo.known_arches)
        try:
            # start with the newest bugs
            for bno in reversed(sorted(bugs)):
                b = get_combined_buginfo(bugs, bno)
                log.info('Bug {} ({})'.format(bno, b.category.name))
                try:
                    plist = dict(match_package_list(repo, b.atoms))

                    for keywords in plist.values():
                        # skip the bug if at least one package has undefined
                        # keywords (i.e. neither explicitly specified nor
                        # arches CC-ed)
                        if not keywords:
                            log.info('Skipping because of incomplete keywords')
                            break
                    else:
                        with git_repo:
                            add_keywords(plist.items(),
                                         b.category == BugCategory.STABLEREQ)

                            check_res, issues = check_dependencies(
                                    repo, plist.items())
                            if check_res:
                                # if nothing changed, do nothing
                                if b.sanity_check is True:
                                    log.info('Still good')
                                    continue

                                # otherwise, update the bug status
                                log.info('All good')
                                # if it was bad before, leave a comment
                                if b.sanity_check is False:
                                    comment = 'All sanity-check issues have been resolved'
                                else:
                                    comment = None
                            else:
                                issues = sorted(str(x) for x in issues)
                                comment = ('Sanity check failed:\n\n'
                                    + '\n'.join(f'> {x}' for x in issues))
                                log.info('Sanity check failed')
                except ParseError as e:
                    log.error(e)
                    check_res = False
                    comment = f'Unable to check for sanity:\n\n> {e}'
                except Exception as e:
                    log.error('TODO: handle exception {} {}'.format(e.__class__, e))
                    continue

                # for negative results, we verify whether the comment
                # needs to change
                if not check_res and b.sanity_check is False:
                    old_comment = bz.get_latest_comment(bno, username)
                    # do not add a second identical comment
                    if (old_comment is not None and comment.strip() ==
                                                    old_comment.strip()):
                        log.info('Failure reported already')
                        continue

                if not self.args.no_update:
                    bz.update_status(bno, check_res, comment)
                    log.info('Bug status updated')
        except GitDirtyWorkTree:
            log.error('{}: working tree is dirty'.format(git_repo))
            raise SystemExit(1)

        return 0


def main(argv):
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
    subp = argp.add_subparsers(title='commands', dest='command',
                               required=True)

    appp = subp.add_parser('apply',
                           help='Keyword/stabilize packages according '
                                'to a bug')
    appp.add_argument('bug', nargs='+', type=int,
                      help='Bug(s) to process')

    prop = subp.add_parser('process-bugs',
                           help='Process all open bugs -- apply '
                                'keywords, test, report results')
    prop.add_argument('-n', '--no-update', action='store_true',
                      help='Do not commit updates to the bugs, only '
                           'check them and report what would be done')

    args = argp.parse_args(argv)
    cmd = NattkaCommands(args)
    try:
        return getattr(cmd, args.command.replace('-', '_'))()
    except SystemExit as e:
        return e.code


if __name__ == '__main__':
    log.setLevel(logging.INFO)
    sys.exit(main(sys.argv[1:]))
