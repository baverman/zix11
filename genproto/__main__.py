import genproto

XCB_PATH = '/usr/share/xcb'
EXTENSIONS = [
    'render.xml',
    'randr.xml',
    'shape.xml',
    'xfixes.xml',
    'dpms.xml',
    'shm.xml',
    'xinput.xml',
    'xkb.xml',
]

if __name__ == '__main__':
    genproto.generate(XCB_PATH, 'xproto.xml', EXTENSIONS, 'src/gen')
