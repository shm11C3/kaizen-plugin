"""Isolate disposable test repositories from an invoking Git hook/worktree.

Git's repository/configuration environment takes precedence over ``git -C``.
This module is only imported by tests, before any fixture Git command runs.
"""
import os


def isolate_git_environment(environ):
    removed = [key for key in environ if key.startswith("GIT_")]
    for key in removed:
        del environ[key]
    return removed


isolate_git_environment(os.environ)
