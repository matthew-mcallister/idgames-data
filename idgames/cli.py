from __future__ import annotations

from dataclasses import dataclass

import click
import requests


def _request(action: str, **params: str) -> requests.Response:
    url = 'https://www.doomworld.com/idgames/api/api.php'
    params = {'out': 'json', 'action': action, **params}
    return requests.get(url, params=params)


@dataclass
class Directory:
    name: str
    subdirs: list[Directory]
    files: list[dict]

    @staticmethod
    def tree(path: str = '') -> Directory:
        def inner(root: str) -> Directory:
            response = _request('getcontents', name=root)
            response.raise_for_status()

            subdirs = []
            try:
                subdirs = response.json()['content']['dir'] or []
                if isinstance(subdirs, dict):
                    subdirs = [subdirs]
            except KeyError:
                pass

            files: list[dict] = []
            try:
                files = response.json()['content']['file'] or []
                if isinstance(files, dict):
                    files = [files]
            except KeyError:
                pass

            subdirs = [inner(dir['name']) for dir in subdirs]
            
            return Directory(root, subdirs, files)

        return inner(path)


@click.group()
def cli():
    pass


@cli.command
@click.argument('paths', nargs=-1)
def tree(paths: list[str]) -> None:
    if not paths:
        paths = ['']

    total_files = 0
    total_dirs = 0

    for path in paths:
        dir = Directory.tree(path)

        def inner(level: int, dir: Directory) -> None:
            print('  ' * level, '└', dir.name, f'({len(dir.files)} files)')
            nonlocal total_files
            nonlocal total_dirs
            total_files += len(dir.files)
            total_dirs += 1
            for sub in dir.subdirs:
                inner(level + 1, sub)

        inner(0, dir)

    print(f'total: {total_dirs} dirs, {total_files} files')


def do_ls(path: str) -> None:
    response = _request('getfiles', name=path)
    response.raise_for_status()
    files = response.json()['content']['file']
    if isinstance(files, dict):
        files = [files]
    for file in files:
        print(file['id'], file['title'])


@cli.command
@click.argument('paths', nargs=-1)
def ls(paths: list[str]) -> None:
    for path in paths:
        do_ls(path)


if __name__ == '__main__':
    cli()