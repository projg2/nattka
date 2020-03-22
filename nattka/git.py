""" Git repository support. """

import subprocess


def git_get_toplevel(repo_path):
    """
    Get top-level working tree path for @repo_path.  Returns None
    when not in repository.
    """

    sp = subprocess.Popen(['git', 'rev-parse', '--show-toplevel'],
                          cwd=repo_path,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    sout, serr = sp.communicate()
    if sp.returncode != 0:
        return None
    return sout.decode().strip()


def git_is_dirty(repo_path):
    """
    Returns True if repository in @repo_path has dirty working tree
    (i.e. calling 'git checkout' will overwrite changes), False
    otherwise.
    """

    sp = subprocess.Popen(['git', 'diff-files', '--quiet'],
                          cwd=repo_path,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    return sp.wait() != 0


def git_reset_changes(repo_path):
    """
    Reset all changes done to the working tree in repository
    at @repo_path.
    """

    sp = subprocess.Popen(['git', 'checkout', '-q', '.'],
                          cwd=git_get_toplevel(repo_path),
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if sp.wait() != 0:
        raise RuntimeError('git checkout failed: {}'
                           .format(stderr.decode()))


class GitDirtyWorkTree(Exception):
    pass


class GitWorkTree(object):
    """
    A context manager factory to obtain 'exclusive' access to a git
    repository and reset changes afterwards.
    """

    def __init__(self, repo_path):
        self.path = git_get_toplevel(repo_path)

    def __enter__(self):
        if git_is_dirty(self.path):
            raise GitDirtyWorkTree(
                'Git working tree {} is dirty'.format(self.path))
        return self

    def __exit__(self, *args):
        git_reset_changes(self.path)
