""" CLI for nattka. """

import argparse
import logging
import os.path
import sys

from nattka.bugzilla import NattkaBugzilla, BugCategory
from nattka.package import (find_repository, match_package_list,
                            add_keywords, fill_keywords)


log = logging.getLogger('nattka')


class NattkaCommands(object):
    def __init__(self, args):
        self.args = args

    def get_api_key(self):
        if self.args.api_key is not None:
            return self.args.api_key
        with open(os.path.expanduser('~/.bugz_token'), 'r') as f:
            return f.read().strip()
        log.error('Please pass --api-key or put it in ~/.bugz_token')
        raise SystemExit(1)

    def process_bug(self):
        repo = find_repository(self.args.repo)

        bz = NattkaBugzilla(self.get_api_key())
        for i, b in enumerate(bz.fetch_package_list(self.args.bug)):
            log.info('Bug {} ({})'.format(self.args.bug[i],
                                          b.category.name))
            plist = dict(fill_keywords(repo,
                                       match_package_list(repo, b.atoms),
                                       b.cc))
            for p, keywords in plist.items():
                log.info('Package {}: {}'.format(p.cpvstr, plist[p]))
            add_keywords(plist.items(), b.category == BugCategory.STABLEREQ)


def main(argv):
    argp = argparse.ArgumentParser()
    argp.add_argument('--api-key',
                      help='Bugzilla API key (read from ~/.bugz_token '
                           'by default')
    argp.add_argument('--repo', default='.',
                      help='Repository path (default: .)')
    subp = argp.add_subparsers(title='commands', dest='command',
                               required=True)

    bugp = subp.add_parser('process-bug',
                           help='Keyword/stabilize packages according '
                                'to a bug')
    bugp.add_argument('bug', nargs='+', type=int,
                      help='Bug(s) to process')

    args = argp.parse_args(argv)
    cmd = NattkaCommands(args)
    return getattr(cmd, args.command.replace('-', '_'))()


if __name__ == '__main__':
    log.setLevel(logging.INFO)
    sys.exit(main(sys.argv[1:]))
