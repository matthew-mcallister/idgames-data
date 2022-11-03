from __future__ import annotations

import io
import struct
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

import click


def c_str(b: bytes) -> str:
    try:
        size = b.index(0)
        b = b[:size]
    except ValueError:
        pass
    return b.decode('ascii')


class Wad:
    iwad: bool
    lumps: list[Lump]
    lump_lookup: dict[str, Lump]

    # Cached lumps
    pnames: list[str] | None

    def __init__(self, data: bytes) -> None:
        magic, size, offset = struct.unpack('4sII', data[:12])
        if magic == b'IWAD':
            iwad = True
        elif magic == b'PWAD':
            iwad = False
        else:
            raise ValueError('Not a WAD')

        self.iwad = iwad

        directory = data[offset:]
        self.lumps = []
        i = 0
        while directory:
            offset, size, name_b = struct.unpack('II8s', directory[:16])
            name = c_str(name_b).upper()
            lump_data = data[offset:offset + size]
            self.lumps.append(Lump(self, name, i, lump_data))
            directory = directory[16:]
            i += 1
        
        self.lump_lookup = {lump.name: lump for lump in self.lumps}
        self.pnames = None
    
    def load_pnames(self) -> list[str]:
        if self.pnames:
            return self.pnames

        lump = self.lump_lookup['PNAMES']
        size, = struct.unpack('I', lump.data[:4])
        pnames = []
        for i in range(size):
            offset = 4 + 8 * i
            pnames.append(c_str(lump.data[offset:offset + 8]))
        self.pnames = pnames
        return pnames


@dataclass
class TexturePatch:
    x: int
    y: int
    patch: str


@dataclass
class Texture:
    name: str
    width: int
    height: int
    patches: list[TexturePatch]

    @staticmethod
    def load_textures(lump: Lump) -> list[Texture]:
        pnames = lump.wad.load_pnames()
        data = lump.data
        dir_len, = struct.unpack('I', data[:4])
        directory: array[int] = array('I', data[4:4 * (dir_len + 1)])
        textures = []
        for offset in directory:
            name_b, pad, width, height, pad2, pcount = struct.unpack('8sIHHIH', data[offset:offset + 22])
            name = c_str(name_b)
            patches = []
            for i in range(pcount):
                poffset = offset + 22 + 10 * i
                x, y, pnum = struct.unpack('HHH', data[poffset:poffset + 6])
                patches.append(TexturePatch(x, y, pnames[pnum]))
            textures.append(Texture(name, width, height, patches))
        return textures
    
    def __str__(self) -> str:
        s = io.StringIO()
        print(self.name, f'{self.width}x{self.height}', file=s)
        for patch in self.patches:
            print(' ', patch.patch, f'{patch.x} {patch.y}', file=s)
        return s.getvalue()


@dataclass
class Lump:
    wad: Wad

    name: str
    position: int
    data: bytes

    def as_textures(self) -> list[Texture]:
        return Texture.load_textures(self)


@click.group()
def cli():
    pass


@cli.command
@click.argument('path')
def dump_textures(path: str) -> None:
    with open(path, 'rb') as f:
        wad = Wad(f.read())
    for name in ('TEXTURE1', 'TEXTURE2'):
        if lump := wad.lump_lookup.get(name):
            try:
                for tex in lump.as_textures():
                    print(tex, end='')
            except Exception as e:
                raise


if __name__ == '__main__':
    cli()