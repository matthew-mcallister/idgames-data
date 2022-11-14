from __future__ import annotations

import difflib
import io
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path
from sys import stderr

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
    lumps: list[Lump] = []
    lump_lookup: dict[str, Lump] = {}

    # Cached lumps
    _pnames: list[str] | None

    def __init__(self) -> None:
        self.iwad = False
        self.lumps = []
        self.lump_lookup = {}
        self._pnames = None

    @staticmethod
    def load(data: bytes) -> Wad:
        wad = Wad()

        magic, size, offset = struct.unpack('4sII', data[:12])
        if magic == b'IWAD':
            iwad = True
        elif magic == b'PWAD':
            iwad = False
        else:
            raise ValueError('Not a WAD')

        wad.iwad = iwad

        directory = data[offset:]
        wad.lumps = []
        i = 0
        while directory:
            offset, size, name_b = struct.unpack('II8s', directory[:16])
            name = c_str(name_b).upper()
            lump_data = data[offset:offset + size]
            wad.lumps.append(Lump(name, i, lump_data))
            directory = directory[16:]
            i += 1
        
        wad.lump_lookup = {lump.name: lump for lump in wad.lumps}

        return wad

    @property
    def pnames(self) -> list[str]:
        if self._pnames:
            return self._pnames
        lump = self.lump_lookup['PNAMES']
        size, = struct.unpack('I', lump.data[:4])
        pnames = []
        for i in range(size):
            offset = 4 + 8 * i
            pnames.append(c_str(lump.data[offset:offset + 8]))
        self._pnames = pnames
        return pnames
        
    def patch(self, pwad: Wad) -> Wad:
        wad = Wad()
        # wad.lumps intentionally left blank
        wad.lump_lookup = {**self.lump_lookup, **pwad.lump_lookup}
        return wad


@dataclass
class Span:
    offset: int
    pixels: bytes

    def to_bytes(self) -> bytes:
        # N.B. in each span, there is an unused byte after the header and an
        # unused byte after the pixel data
        return struct.pack('BBB', self.offset, len(self.pixels), 0) \
            + self.pixels \
            + b'\x00'


@dataclass
class Patch:
    width: int
    height: int
    x: int
    y: int
    columns: list[list[Span]]

    @staticmethod
    def from_bytes(data: bytes) -> Patch:
        width, height, x, y = struct.unpack('HHhh', data[:8])
        columns = []
        for i in range(width):
            pofs = 8 + 4 * i
            ofs: int
            ofs, = struct.unpack('I', data[pofs:pofs + 4])

            spans = []
            while True:
                if data[ofs] == 0xff:
                    break

                offset, size = struct.unpack('BB', data[ofs:ofs + 2])
                ofs += 3
                spans.append(Span(offset, data[ofs:ofs + size]))
                ofs += size + 1
            
            columns.append(spans)
        
        return Patch(width=width, height=height, x=x, y=y, columns=columns)
            
    def to_bytes(self) -> bytes:
        header = struct.pack('HHhh', self.width, self.height, self.x, self.y)

        columns: list[bytes] = []
        for col in self.columns:
            spans = [span.to_bytes() for span in col]
            columns.append(b''.join([*spans, b'\xff']))

        # Compute column offset table
        pointers = bytearray(4 * self.width)
        offset = len(header) + len(pointers)
        for i, col in enumerate(columns):
            struct.pack_into('I', pointers, 4 * i, offset)
            offset += len(col)
        
        return b''.join([header, pointers, *columns])


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
    def load_textures(wad: Wad, data: bytes) -> list[Texture]:
        pnames = wad.pnames
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
    name: str
    position: int
    data: bytes

    def as_patch(self) -> Patch:
        return Patch.from_bytes(self.data)

    def as_textures(self, wad: Wad) -> list[Texture]:
        return Texture.load_textures(wad, self.data)


@click.group()
def cli():
    pass


@cli.command
@click.argument('path')
def dump_textures(path: str) -> None:
    wad = Wad.load(Path(path).read_bytes())
    for name in ('TEXTURE1', 'TEXTURE2'):
        if lump := wad.lump_lookup.get(name):
            try:
                for tex in lump.as_textures(wad):
                    print(tex, end='')
            except Exception as e:
                raise


@cli.command
@click.argument('path')
@click.option('--iwad', '-i')
def test_patches(path: str, iwad: str | None) -> None:
    wad = Wad.load(Path(path).read_bytes())
    if iwad:
        _iwad = Wad.load(Path(iwad).read_bytes())
        wad = _iwad.patch(wad)
    for name in wad.pnames:
        try:
            lump = wad.lump_lookup[name]
            patch = lump.as_patch()
            round_trip = patch.to_bytes()
            if len(lump.data) != len(round_trip):
                raise ValueError(f'original len: {len(lump.data)}, round trip len: {len(round_trip)}')
        except Exception as e:
            print(f'Error in patch {name}:', e, file=stderr)


if __name__ == '__main__':
    cli()