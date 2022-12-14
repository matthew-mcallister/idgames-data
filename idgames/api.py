from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import click
import requests

from idgames import ROOT_DIR


def _request(action: str, **params: str) -> requests.Response:
    url = 'https://www.doomworld.com/idgames/api/api.php'
    params = {'out': 'json', 'action': action, **params}
    return requests.get(url, params=params)


MIRRORS = [
    'http://mirrors.syringanetworks.net/idgames',
    'https://youfailit.net/pub/idgames',
    'https://www.gamers.org/pub/idgames',
]

MIRROR = MIRRORS[0]


DOWNLOAD_DIR = ROOT_DIR / 'download'
WAD_DIR = ROOT_DIR / 'wads'


@dataclass
class File:
    id: int
    title: str
    dir: str
    filename: str
    size: int
    age: int
    date: str
    author: str
    email: str
    url: str
    idgamesurl: str
    description: str
    textfile: str | None = None
    credits: str | None = None
    base: str | None = None
    buildtime: str | None = None
    editors: str | None = None
    bugs: str | None = None
    rating: float | None = None
    votes: int | None = None

    @property
    def download_url(self) -> str:
        return MIRROR + '/' + self.dir + '/' + self.filename

    @property
    def download_path(self) -> Path:
        filename = (self.dir + '/' + self.filename).replace('/', '::')
        return DOWNLOAD_DIR / filename


@dataclass
class Directory:
    name: str
    subdirs: list[Directory]
    files: list[File]

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
            
            return Directory(root, subdirs, [File(**file) for file in files])

        return inner(path)
    
    def files_recursive(self) -> Iterator[File]:
        for file in self.files:
            yield file
        for sub in self.subdirs:
            yield from sub.files_recursive()


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
    total_size = 0

    for path in paths:
        dir = Directory.tree(path)

        def inner(level: int, dir: Directory) -> None:
            print('  ' * level, '???', dir.name, f'({len(dir.files)} files)')
            nonlocal total_files
            nonlocal total_dirs
            nonlocal total_size
            total_files += len(dir.files)
            total_dirs += 1
            total_size += sum(file.size for file in dir.files)
            for sub in dir.subdirs:
                inner(level + 1, sub)

        inner(0, dir)

    mb = int(total_size / 2**20)
    print(f'total: {total_dirs} dirs, {total_files} files, {mb} megabytes')


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


@cli.command
@click.argument('ids', nargs=-1)
@click.option('--verbose/--no-verbose', '-v', default=False)
def file(ids: list[str], verbose: bool) -> None:
    FIELDS = [
        'id', 'title', 'dir', 'filename', 'size', 'age', 'date', 'author',
        'email', 'credits', 'base', 'buildtime', 'editors', 'bugs', 'rating',
        'votes', 'url', 'idgamesurl',
    ]
    for id in ids:
        response = _request('get', id=id)
        response.raise_for_status()
        file = response.json()['content']
        print(f"{file['title']} ({file['id']})")
        for field in FIELDS:
            if field in file:
                print(f'{field}: {file[field]}')
        if verbose:
            print('description', file['description'])
            print(file['textfile'])
        else:
            print('description:', file['description'].split('\n', 1)[0] + '...')


def sizeof_fmt(num, suffix="B"):
    """Copyright Fred Cirera according to StackOverflow."""
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f'{num:.1f}Yi{suffix}'


@cli.command
@click.argument('path')
@click.option('--mirror', '-m', default=0)
def fetch(path: str, mirror: int) -> None:
    global MIRROR
    MIRROR = MIRRORS[mirror]

    root = Directory.tree(path)
    all_files = list(root.files_recursive())
    files_to_fetch: list[File] = []
    for file in all_files:
        if not file.download_path.exists():
            files_to_fetch.append(file)
    count = len(files_to_fetch)
    for i, file in enumerate(files_to_fetch):
        print(f'{i}/{count}', sizeof_fmt(file.size), file.id, file.title)
        response = requests.get(file.download_url)
        response.raise_for_status()
        file.download_path.parent.mkdir(parents=True, exist_ok=True)
        file.download_path.write_bytes(response.content)


def extract_zip(path: Path) -> None:
    zip = zipfile.ZipFile(path)
    for info in zip.infolist():
        fname = info.filename.lower()
        if fname.endswith(('.wad', '.pk3')):
            info.filename = path.with_suffix('').name + '::' + fname.replace('/', '::')
            zip.extract(info, WAD_DIR)


@cli.command
def extract() -> None:
    """Extracts all WAD and PK3 files from the zip files under the default
    download directory.
    """
    WAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in (DOWNLOAD_DIR).iterdir():
        try:
            extract_zip(path)
        except Exception as e:
            print(f'Failed to extract {path}: {e}')


if __name__ == '__main__':
    cli()