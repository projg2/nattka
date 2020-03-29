""" CLI for nattka. """

import argparse
import logging
import os.path
import sys

from nattka.bugzilla import (NattkaBugzilla, BugCategory,
                             fill_keywords_from_cc)
from nattka.package import (find_repository, match_package_list,
                            add_keywords)


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

    def apply(self):
        repo = find_repository(self.args.repo)

        bz = NattkaBugzilla(self.get_api_key())
        for bugno, b in bz.fetch_package_list(self.args.bug).items():
            b = fill_keywords_from_cc(b, repo.known_arches)
            log.info('Bug {} ({})'.format(bugno, b.category.name))
            plist = dict(match_package_list(repo, b.atoms))
            for p, keywords in plist.items():
                log.info('Package {}: {}'.format(p.cpvstr, plist[p]))
            add_keywords(plist.items(), b.category == BugCategory.STABLEREQ)

    def process_bugs(self):
        pass


def main(argv):
    argp = argparse.ArgumentParser()
    argp.add_argument('--api-key',
                      help='Bugzilla API key (read from ~/.bugz_token '
                           'by default')
    argp.add_argument('--repo', default='.',
                      help='Repository path (default: .)')
    subp = argp.add_subparsers(title='commands', dest='command',
                               required=True)

    appp = subp.add_parser('apply',
                           help='Keyword/stabilize packages according '
                                'to a bug')
    appp.add_argument('bug', nargs='+', type=int,
                      help='Bug(s) to process')

    args = argp.parse_args(argv)
    cmd = NattkaCommands(args)
    return getattr(cmd, args.command.replace('-', '_'))()


if __name__ == '__main__':
    log.setLevel(logging.INFO)
    sys.exit(main(sys.argv[1:]))
