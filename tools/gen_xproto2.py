#!/usr/bin/env python3

from __future__ import annotations
import io
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager

import xcbxml

XML_PATH = Path("/usr/share/xcb/xproto.xml")
OUT_PATH = Path("src/xproto.zig")
TARGET_REQUESTS = ("InternAtom", "GetProperty", "GetInputFocus", "CreateWindow", "MapWindow")


class Printer:
    def __init__(self, buf):
        self.buf = buf
        self.level = 0

    def __call__(self, *args):
        if self.level >= 1:
            level = '    ' * (self.level - 1) + '   '
            print(level, *args, file=self.buf)
        else:
            print(*args, file=self.buf)

    @contextmanager
    def nest(self):
        self.level += 1
        yield
        self.level -= 1

    @contextmanager
    def reset(self):
        oldlevel = self.level
        self.level = 0
        yield
        self.level = oldlevel


@dataclass
class Field:
    name: str
    typ: Type

    @staticmethod
    def parse(item) -> Field:
        assert not list(item), ET.tostring(item)
        # TODO: add format check
        return Field(item.attrib['name'], item.attrib['type'], item.attrib['type'])


@dataclass
class Pad:
    count: int

    @staticmethod
    def parse(item) -> Pad:
        assert set(item.attrib) == {'bytes'}
        assert not list(item)
        return Pad(int(item.attrib['bytes']))


class Gen:
    def __init__(self, path: str):
        self.buf = io.StringIO()
        self.printer = Printer(self.buf)
        self.print = self.printer.__call__

        root = ET.parse(path).getroot()
        desc = xcbxml.root_item.match(root)
        from pprint import pprint
        pprint(desc)
        1/0

        self.items = {}
        for it in root:
            self.items.setdefault(it.tag, {})[it.attrib.get('name') or it.attrib['newname']] = it

        self.print('// GENERATED\n')
        for name in TARGET_REQUESTS:
            self.emit_request(self.items['request'][name])

    def get_fields(self, item):
        result = []
        for it in item:
            if it.tag == 'field':
                result.append(Field.parse(it))
            elif it.tag == 'pad':
                result.append(Pad.parse(it))
            elif it.tag == 'list':
                result.append(ListField.parse(it))
            else:
                raise Exception(f'Unknown field: {ET.tostring(it)}')

    def emit_request(self, item):
        assert set(item.attrib) == {'name', 'opcode'}, item.attrib

        fields = self.get_fields(item)

        self.print(f'const {item.attrib['name']}Request = struct {{')
        self.print('};\n')
        print(item.attrib, list(item))


def main():
    g = Gen(XML_PATH)
    # print(g.buf.getvalue())


if __name__ == '__main__':
    main()
