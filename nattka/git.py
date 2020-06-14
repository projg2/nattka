# (c) 2020 Michał Górny
# 2-clause BSD license

""" Git repository support. """

import subprocess
import typing

from types import TracebackType

from pathlib import Path


class GitCommitNoChanges(Exception):
    pass


def git_get_toplevel(repo_path: Path
                     ) -> typing.Optional[Path]:
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
    return Path(sout.decode().strip())


def git_is_dirty(repo_path: Path
                 ) -> bool:
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


def git_commit(repo_path: Path,
               commit_message: str,
               files: typing.Iterable[str] = []
               ) -> str:
    """
    Commit specified changes in the git repository

    Commit changes in the repository found in directory `repo_path`,
    using `commit_message`.  `files` specify the list of files
    (relative to top directory of git checkout) to commit; if empty,
    all changed files are committed.  Return the 'git commit' output
    (short commit summary).
    """

    sp = subprocess.Popen(['git', 'diff', '--quiet', '--exit-code',
                           'HEAD', '--']
                          + list(files),
                          cwd=git_get_toplevel(repo_path))
    if sp.wait() == 0:
        raise GitCommitNoChanges(f'No changes found in files: '
                                 f'{" ".join(files)}')

    sp = subprocess.Popen(['git', 'commit', '-s', '-m', commit_message]
                          + list(files),
                          cwd=git_get_toplevel(repo_path),
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    sout, _ = sp.communicate()
    if sp.wait() != 0:
        raise RuntimeError(f'git commit failed: {sout.decode()}')
    return sout.decode()


def git_reset_changes(repo_path: Path
                      ) -> None:
    """
    Reset all changes done to the working tree in repository
    at @repo_path.
    """

    sp = subprocess.Popen(['git', 'checkout', '-q', '.'],
                          cwd=git_get_toplevel(repo_path),
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    sout, _ = sp.communicate()
    if sp.wait() != 0:
        raise RuntimeError(f'git checkout failed: {sout.decode()}')


class GitRepositoryNotFound(Exception):
    pass


class GitDirtyWorkTree(Exception):
    pass


class GitWorkTree(object):
    """
    A context manager factory to obtain 'exclusive' access to a git
    repository and reset changes afterwards.
    """

    path: Path

    def __init__(self,
                 repo_path: Path):
        path = git_get_toplevel(repo_path)
        if path is None:
            raise GitRepositoryNotFound(
                f'No repository found in {repo_path}')
        else:
            self.path = path

    def __enter__(self) -> 'GitWorkTree':
        if git_is_dirty(self.path):
            raise GitDirtyWorkTree(
                f'Git working tree {self.path} is dirty')
        return self

    def __exit__(self,
                 exc_type: typing.Optional[typing.Type[BaseException]],
                 exc_val: typing.Optional[BaseException],
                 exc_tb: typing.Optional[TracebackType]
                 ) -> None:
        git_reset_changes(self.path)
