from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, TypeVar, Self, Sequence
import xml.etree.ElementTree as ET


from schema import (
    Item,
    one_of,
    Many,
    Seq,
    StructItem,
    Ref,
    TextItem,
    IgnoreItem,
    Node,
    TextNode,
    OneOf,
    Opt,
)

T = TypeVar('T')

Attrs = dict[str, object]


def node_text(attrs: Attrs, value: str) -> str:
    return value


def node_int(attrs: Attrs, value: str) -> int:
    return int(value)


def simple(typ: type[T], kids_name: str | None = None) -> Callable[[Attrs], object]:
    def make(attrs: Attrs) -> T:
        if kids_name:
            attrs[kids_name] = attrs.pop('@kids')
        return typ(**attrs)

    return make


@dataclass
class Field:
    name: str
    type: str
    mask: str | None = None
    enum: str | None = None
    altenum: str | None = None


@dataclass
class ListField:
    name: str
    item_type: str
    len_expr: None | FieldRef | Op | int
    enum: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> ListField:
        attrs['item_type'] = attrs.pop('type')
        kids = attrs.pop('@kids')
        attrs['len_expr'] = kids and kids[0]  # type: ignore[index]
        return ListField(**attrs)  # type: ignore[arg-type]


@dataclass
class SwitchField:
    name: str
    fieldref: FieldRef
    items: list[SwitchItem]

    @staticmethod
    def make(attrs: Attrs) -> SwitchField:
        kids = attrs.pop('@kids')
        attrs['fieldref'] = kids.pop('fieldref') # type: ignore[attr-defined]
        attrs['items'] = kids.pop('bitcase')  # type: ignore[attr-defined]
        return SwitchField(**attrs)  # type: ignore[arg-type]


@dataclass
class SwitchItem:
    enum_ref: tuple[str, str]
    field: Field

    @staticmethod
    def make(attrs: Attrs) -> SwitchItem:
        kids = attrs.pop('@kids')
        enumref: TextNode = kids.pop('enumref')  # type: ignore[attr-defined]
        attrs['enum_ref'] = enumref.attrs['ref'], enumref.value
        attrs['field'] = kids.pop('field')  # type: ignore[attr-defined]
        assert not kids
        return SwitchItem(**attrs)  # type: ignore[arg-type]


@dataclass
class Pad:
    count: int | None = None
    align: int | None = None

    @staticmethod
    def make(attrs: Attrs) -> Pad:
        if 'bytes' in attrs:
            attrs['count'] = int(attrs.pop('bytes'))  # type: ignore[call-overload]
        obj = Pad(**attrs)  # type: ignore[arg-type]
        assert obj.count or obj.align
        return obj


@dataclass
class Fd:
    name: str


DataFields = Field | ListField | Pad | Fd
RequestDataFields = DataFields | SwitchField

@dataclass
class Reply:
    fields: Sequence[DataFields]


@dataclass
class Struct:
    name: str
    fields: Sequence[DataFields]


@dataclass
class Enum:
    name: str
    fields: Sequence[EnumItem]


@dataclass
class EnumItem:
    name: str
    value: int

    @staticmethod
    def make(attrs: Attrs) -> EnumItem:
        k: TextNode
        (k,) = attrs.pop('@kids')  # type: ignore[misc]
        if k.tag == 'bit':
            v = 1 << int(k.value)
        elif k.tag == 'value':
            v = int(k.value)
        else:
            raise RuntimeError(f'Unexpected enum item type: {k.tag}')
        attrs['value'] = v
        return EnumItem(**attrs)  # type: ignore[arg-type]


@dataclass
class Union:
    name: str
    fields: Sequence[DataFields]


@dataclass
class Error:
    name: str
    number: str
    fields: Sequence[DataFields]


@dataclass
class Request:
    name: str
    opcode: str
    reply: Reply | None
    fields: Sequence[RequestDataFields]
    combine_adjacent: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> Request:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        kids = attrs.pop('@kids')
        attrs['reply'] = kids.pop('reply')  # type: ignore[attr-defined]
        attrs['fields'] = kids.pop('_')  # type: ignore[attr-defined]
        return Request(**attrs)  # type: ignore[arg-type]

    @property
    def has_fd(self) -> bool:
        if any(isinstance(field, Fd) for field in self.fields):
            return True
        return self.reply is not None and any(isinstance(field, Fd) for field in self.reply.fields)


@dataclass
class Event:
    name: str
    number: str
    fields: Sequence[DataFields]
    no_sequence_number: str | None = None
    xge: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> Event:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        attrs['fields'] = attrs.pop('@kids')
        return Event(**attrs)  # type: ignore[arg-type]


@dataclass
class EventCopy:
    name: str
    number: str
    ref: str


@dataclass
class ErrorCopy:
    name: str
    number: str
    ref: str


@dataclass
class XidType:
    name: str


@dataclass
class XidUnion:
    name: str
    fields: list[str]


@dataclass
class TypeDef:
    name: str
    alias: str

    @staticmethod
    def make(attrs: Attrs) -> TypeDef:
        attrs['name'] = attrs.pop('newname')
        attrs['alias'] = attrs.pop('oldname')
        return TypeDef(**attrs)  # type: ignore[arg-type]


@dataclass
class FieldRef:
    ref: str

    @staticmethod
    def make(attrs: Attrs, value: str) -> FieldRef:
        return FieldRef(value)


@dataclass
class Op:
    op: str
    left: int | FieldRef | Op
    right: int | FieldRef | Op

    @staticmethod
    def make(attrs: Attrs) -> Op:
        left, right = attrs.pop('@kids')  # type: ignore[misc]
        return Op(**attrs, left=left, right=right)  # type: ignore[arg-type, has-type]


fieldref_item = TextItem('fieldref', cnv=FieldRef.make)

list_items_ref = Ref[OneOf]('list_items')
list_items = one_of(
    fieldref_item,
    TextItem('value', cnv=node_int),
    Item('op', {'op'}, Seq(list_items_ref, list_items_ref), cnv=Op.make),
)

field_item = Item('field', {'type', 'name', 'mask', 'enum', 'altenum'}, cnv=simple(Field))

bitcase = Item(
    'bitcase',
    set(),
    StructItem(enumref=TextItem('enumref', {'ref'}), field=field_item),
    cnv=SwitchItem.make,
)

switch = Item[SwitchField](
    'switch',
    {'name'},
    StructItem(fieldref=fieldref_item, bitcase=Many(bitcase)),
    cnv=SwitchField.make,
)

field_items_tup = (
    field_item,
    Item('pad', {'bytes', 'align'}, cnv=Pad.make),
    Item('list', {'type', 'name', 'enum'}, Seq(list_items, optional=True), cnv=ListField.make),
    Item('fd', {'name'}, cnv=simple(Fd)),
    IgnoreItem('doc'),
)
field_items = one_of(*field_items_tup)
request_field_items = one_of(switch, *field_items_tup)

reply = Item('reply', set(), Many(field_items), cnv=simple(Reply, 'fields'))

enum_items = one_of(
    Item(
        'item',
        {'name'},
        Seq(one_of(TextItem('bit'), TextItem('value'))),
        cnv=EnumItem.make,
    ),
    IgnoreItem('doc'),
)

request = Item(
    'request',
    {'name', 'opcode', 'combine-adjacent'},
    StructItem(reply=Opt(reply), _=Many(request_field_items)),
    cnv=Request.make,
)

struct = Item('struct', {'name'}, Many(field_items), cnv=simple(Struct, 'fields'))

xidtype = Item('xidtype', {'name'}, cnv=simple(XidType))

xidunion = Item(
    'xidunion',
    {'name'},
    Many(TextItem('type', cnv=node_text)),
    cnv=simple(XidUnion, 'fields'),
)

typedef = Item('typedef', {'oldname', 'newname'}, cnv=TypeDef.make)

enum = Item('enum', {'name'}, Many(enum_items), cnv=simple(Enum, 'fields'))

event = Item(
    'event',
    {'name', 'number', 'no-sequence-number', 'xge'},
    Many(field_items),
    cnv=Event.make,
)

eventcopy = Item('eventcopy', {'name', 'number', 'ref'}, cnv=simple(EventCopy))

union = Item('union', {'name'}, Many(field_items), cnv=simple(Union, 'fields'))

error = Item('error', {'name', 'number'}, Many(field_items), cnv=simple(Error, 'fields'))

errorcopy = Item('errorcopy', {'name', 'number', 'ref'}, cnv=simple(ErrorCopy))


@dataclass
class Bindings:
    header: str
    imports: list[str]
    request: list[Request]
    struct: list[Struct]
    xidtype: list[XidType]
    xidunion: list[XidUnion]
    typedef: list[TypeDef]
    enum: list[Enum]
    event: list[Event]
    eventcopy: list[EventCopy]
    union: list[Union]
    error: list[Error]
    errorcopy: list[ErrorCopy]
    extension_xname: str | None = None
    extension_name: str | None = None
    major_version: str | None = None
    minor_version: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> Bindings:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        attrs.update(attrs.pop('@kids'))  # type: ignore[call-overload]
        attrs['imports'] = attrs.pop('import')
        attrs['request'] = [request for request in attrs['request'] if not request.has_fd]  # type: ignore[index]
        return Bindings(**attrs)  # type: ignore[arg-type]


import_item = TextItem('import', cnv=node_text)

root_item = Item(
    'xcb',
    {'header', 'extension-xname', 'extension-name', 'major-version', 'minor-version'},
    StructItem(
        request=Many(request),
        struct=Many(struct),
        xidtype=Many(xidtype),
        xidunion=Many(xidunion),
        typedef=Many(typedef),
        enum=Many(enum),
        event=Many(event),
        eventcopy=Many(eventcopy),
        union=Many(union),
        error=Many(error),
        errorcopy=Many(errorcopy),
        **{'import': Many(import_item)},
    ),
    cnv=Bindings.make,
)
