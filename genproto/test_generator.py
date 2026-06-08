#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

import genproto


def main() -> None:
    out_dir = Path('src/testgen')
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / '_ext.zig').write_text('pub const Extension = enum {\n    CORE,\n    FOO,\n};\n')

    genproto.generate(
        directory=Path('genproto/testdata'),
        core_xml_filename='core.xml',
        extension_xml_names=['foo.xml'],
        output_directory=out_dir,
        ext_import='_ext.zig',
    )


if __name__ == '__main__':
    main()
