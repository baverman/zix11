from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Sequence, TypeAlias, TypeVar, cast

from .schema import (
    IgnoreItem,
    Item,
    Many,
    OneOf,
    Opt,
    Ref,
    Seq,
    StructItem,
    TextItem,
    TextNode,
    one_of,
)

T = TypeVar('T')

Attrs = dict[str, object]
if TYPE_CHECKING:
    ListExpr: TypeAlias = (
        'int | FieldRef | ParamRef | Op | Unop | SumOf | PopCount | ListElementRef'
    )
else:
    ListExpr = object


def cast_kids(attrs: Attrs) -> list[object]:
    return cast(list[object], attrs.pop('@kids'))


def cast_kid_map(attrs: Attrs) -> dict[str, object]:
    return cast(dict[str, object], attrs.pop('@kids'))


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
    altmask: str | None = None


@dataclass
class ListField:
    name: str
    item_type: str
    len_expr: None | ListExpr
    enum: str | None = None
    mask: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> ListField:
        attrs['item_type'] = attrs.pop('type')
        kids = cast_kids(attrs)
        attrs['len_expr'] = kids[0] if kids else None
        return ListField(**attrs)  # type: ignore[arg-type]


@dataclass
class SwitchField:
    name: str
    expr: ListExpr
    items: list[SwitchItem]

    @staticmethod
    def make(attrs: Attrs) -> SwitchField:
        kids = cast(dict[str, list[object]], cast_kid_map(attrs))
        attrs['expr'] = kids.pop('_')[0]
        attrs['items'] = kids.pop('bitcase')
        return SwitchField(**attrs)  # type: ignore[arg-type]


@dataclass
class SwitchItem:
    enum_refs: Sequence[tuple[str, str]]
    fields: Sequence[RequestDataFields | RequiredStartAlign]
    name: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> SwitchItem:
        kids = attrs.pop('@kids')
        enumrefs: list[TextNode] = kids.pop('enumref')  # type: ignore[attr-defined]
        attrs['enum_refs'] = [(enumref.attrs['ref'], enumref.value) for enumref in enumrefs]
        attrs['fields'] = kids.pop('_')  # type: ignore[attr-defined]
        assert not kids
        return SwitchItem(**attrs)  # type: ignore[arg-type]


@dataclass
class RequiredStartAlign:
    align: int
    offset: int

    @staticmethod
    def make(attrs: Attrs) -> RequiredStartAlign:
        return RequiredStartAlign(
            align=int(cast(str, attrs['align'])),
            offset=int(cast(str, attrs['offset'])),
        )


@dataclass
class CaseItem:
    enum_ref: tuple[str, str]
    fields: Sequence[RequestDataFields | RequiredStartAlign]
    name: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> CaseItem:
        kids = attrs.pop('@kids')
        enumref: TextNode = kids.pop('enumref')  # type: ignore[attr-defined]
        attrs['enum_ref'] = enumref.attrs['ref'], enumref.value
        attrs['fields'] = kids.pop('_')  # type: ignore[attr-defined]
        return CaseItem(**attrs)  # type: ignore[arg-type]


@dataclass
class CaseSwitchField:
    name: str
    fieldref: FieldRef
    items: list[CaseItem]
    required_start_align: list[RequiredStartAlign]

    @staticmethod
    def make(attrs: Attrs) -> CaseSwitchField:
        kids = attrs.pop('@kids')
        attrs['fieldref'] = kids.pop('fieldref')  # type: ignore[attr-defined]
        attrs['items'] = kids.pop('case')  # type: ignore[attr-defined]
        attrs['required_start_align'] = kids.pop('required_start_align')  # type: ignore[attr-defined]
        return CaseSwitchField(**attrs)  # type: ignore[arg-type]


@dataclass
class Pad:
    count: int | None = None
    align: int | None = None

    @staticmethod
    def make(attrs: Attrs) -> Pad:
        attrs.pop('serialize', None)
        if 'bytes' in attrs:
            attrs['count'] = int(attrs.pop('bytes'))  # type: ignore[call-overload]
        obj = Pad(**attrs)  # type: ignore[arg-type]
        assert obj.count or obj.align
        return obj


@dataclass
class Fd:
    name: str


DataFields = Field | ListField | Pad | Fd
RequestDataFields = DataFields | SwitchField | CaseSwitchField


@dataclass
class Reply:
    fields: Sequence[DataFields]


@dataclass
class Struct:
    name: str
    fields: Sequence[DataFields | CaseSwitchField | RequiredStartAlign]
    length_expr: None | ListExpr = None

    @staticmethod
    def make(attrs: Attrs) -> Struct:
        kids = attrs.pop('@kids')
        attrs['length_expr'] = kids.pop('length')  # type: ignore[attr-defined]
        attrs['fields'] = kids.pop('_')  # type: ignore[attr-defined]
        return Struct(**attrs)  # type: ignore[arg-type]


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
    length_expr: None | ListExpr = None

    @staticmethod
    def make(attrs: Attrs) -> Request:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        kids = attrs.pop('@kids')
        attrs['length_expr'] = kids.pop('length')  # type: ignore[attr-defined]
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
    fields: Sequence[DataFields | CaseSwitchField | RequiredStartAlign]
    no_sequence_number: str | None = None
    xge: str | None = None
    length_expr: None | ListExpr = None

    @staticmethod
    def make(attrs: Attrs) -> Event:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        kids = attrs.pop('@kids')
        attrs['length_expr'] = kids.pop('length')  # type: ignore[attr-defined]
        attrs['fields'] = kids.pop('_')  # type: ignore[attr-defined]
        return Event(**attrs)  # type: ignore[arg-type]


@dataclass
class EventCopy:
    name: str
    number: str
    ref: str


@dataclass
class AllowedEvent:
    extension: str
    xge: str
    opcode_min: str
    opcode_max: str

    @staticmethod
    def make(attrs: Attrs) -> AllowedEvent:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        return AllowedEvent(**attrs)  # type: ignore[arg-type]


@dataclass
class EventStruct:
    name: str
    allowed: list[AllowedEvent]

    @staticmethod
    def make(attrs: Attrs) -> EventStruct:
        kids = attrs.pop('@kids')
        attrs['allowed'] = kids.pop('allowed')  # type: ignore[attr-defined]
        return EventStruct(**attrs)  # type: ignore[arg-type]


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
class ParamRef:
    ref: str
    type: str

    @staticmethod
    def make(attrs: Attrs, value: str) -> ParamRef:
        return ParamRef(ref=value, type=attrs['type'])  # type: ignore[arg-type]


@dataclass
class Op:
    op: str
    left: ListExpr
    right: ListExpr

    @staticmethod
    def make(attrs: Attrs) -> Op:
        left, right = cast_kids(attrs)
        return Op(**attrs, left=cast(ListExpr, left), right=cast(ListExpr, right))  # type: ignore[arg-type]


@dataclass
class Unop:
    op: str
    expr: ListExpr

    @staticmethod
    def make(attrs: Attrs) -> Unop:
        (expr,) = cast_kids(attrs)
        return Unop(**attrs, expr=cast(ListExpr, expr))  # type: ignore[arg-type]


@dataclass
class ListElementRef:
    @staticmethod
    def make(attrs: Attrs) -> ListElementRef:
        _ = attrs
        return ListElementRef()


@dataclass
class PopCount:
    expr: ListExpr

    @staticmethod
    def make(attrs: Attrs) -> PopCount:
        (expr,) = cast_kids(attrs)
        return PopCount(expr=cast(ListExpr, expr))


@dataclass
class SumOf:
    ref: str
    expr: ListExpr

    @staticmethod
    def make(attrs: Attrs) -> SumOf:
        kids = cast_kids(attrs)
        expr = cast(ListExpr, kids[0]) if kids else ListElementRef()
        return SumOf(ref=attrs['ref'], expr=expr)  # type: ignore[arg-type]


fieldref_item = TextItem('fieldref', cnv=FieldRef.make)
paramref_item = TextItem('paramref', {'type'}, cnv=ParamRef.make)
listelement_ref_item = Item('listelement-ref', set(), cnv=ListElementRef.make)

list_items_ref = Ref[OneOf]('list_items')
list_items = one_of(
    fieldref_item,
    paramref_item,
    TextItem('value', cnv=node_int),
    Item('op', {'op'}, Seq(list_items_ref, list_items_ref), cnv=Op.make),
    Item('unop', {'op'}, Seq(list_items_ref), cnv=Unop.make),
    Item('popcount', set(), Seq(list_items_ref), cnv=PopCount.make),
    Item('sumof', {'ref'}, Seq(list_items_ref, optional=True), cnv=SumOf.make),
    listelement_ref_item,
)

field_item = Item(
    'field', {'type', 'name', 'mask', 'enum', 'altenum', 'altmask'}, cnv=simple(Field)
)
required_start_align_item = Item(
    'required_start_align',
    {'align', 'offset'},
    cnv=RequiredStartAlign.make,
)
case_items_ref = Ref[OneOf]('case_items')

bitcase = Item(
    'bitcase',
    {'name'},
    StructItem(enumref=Many(TextItem('enumref', {'ref'})), _=Many(case_items_ref)),
    cnv=SwitchItem.make,
)

case = Item(
    'case',
    {'name'},
    StructItem(enumref=TextItem('enumref', {'ref'}), _=Many(case_items_ref)),
    cnv=CaseItem.make,
)

switch = Item[SwitchField](
    'switch',
    {'name'},
    StructItem(_=Many(list_items), bitcase=Many(bitcase)),
    cnv=SwitchField.make,
)

case_switch = Item[CaseSwitchField](
    'switch',
    {'name'},
    StructItem(
        fieldref=fieldref_item,
        required_start_align=Many(required_start_align_item),
        case=Many(case),
    ),
    cnv=CaseSwitchField.make,
)

case_items = one_of(
    field_item,
    Item('pad', {'bytes', 'align', 'serialize'}, cnv=Pad.make),
    Item(
        'list', {'type', 'name', 'enum', 'mask'}, Seq(list_items, optional=True), cnv=ListField.make
    ),
    Item('fd', {'name'}, cnv=simple(Fd)),
    required_start_align_item,
    switch,
    case_switch,
    IgnoreItem('doc'),
)

field_items_tup = (
    case_switch,
    switch,
    field_item,
    Item('pad', {'bytes', 'align', 'serialize'}, cnv=Pad.make),
    Item(
        'list', {'type', 'name', 'enum', 'mask'}, Seq(list_items, optional=True), cnv=ListField.make
    ),
    Item('fd', {'name'}, cnv=simple(Fd)),
    required_start_align_item,
    IgnoreItem('doc'),
)
field_items = one_of(*field_items_tup)
request_field_items = field_items
length_item = Item('length', set(), Seq(list_items), cnv=lambda attrs: attrs['@kids'][0])  # type: ignore[index]

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
    StructItem(length=Opt(length_item), reply=Opt(reply), _=Many(request_field_items)),
    cnv=Request.make,
)

struct = Item(
    'struct', {'name'}, StructItem(length=Opt(length_item), _=Many(field_items)), cnv=Struct.make
)

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
    StructItem(length=Opt(length_item), _=Many(field_items)),
    cnv=Event.make,
)

eventcopy = Item('eventcopy', {'name', 'number', 'ref'}, cnv=simple(EventCopy))
allowed_event = Item(
    'allowed',
    {'extension', 'xge', 'opcode-min', 'opcode-max'},
    cnv=AllowedEvent.make,
)
eventstruct = Item(
    'eventstruct',
    {'name'},
    StructItem(allowed=Many(allowed_event)),
    cnv=EventStruct.make,
)

union = Item('union', {'name'}, Many(field_items), cnv=simple(Union, 'fields'))

error = Item('error', {'name', 'number'}, Many(field_items), cnv=simple(Error, 'fields'))

errorcopy = Item('errorcopy', {'name', 'number', 'ref'}, cnv=simple(ErrorCopy))


@dataclass
class Bindings:
    header: str
    decls: list[object]
    imports: list[str]
    extension_xname: str | None = None
    extension_name: str | None = None
    major_version: str | None = None
    minor_version: str | None = None

    @staticmethod
    def make(attrs: Attrs) -> Bindings:
        attrs = {k.replace('-', '_'): v for k, v in attrs.items()}
        decls = []
        imports = []
        for item in cast_kids(attrs):
            if isinstance(item, str):
                imports.append(item)
            else:
                decls.append(item)
        attrs['decls'] = decls
        attrs['imports'] = imports
        attrs['decls'] = [decl for decl in decls if not (isinstance(decl, Request) and decl.has_fd)]
        return Bindings(**attrs)  # type: ignore[arg-type]


import_item = TextItem('import', cnv=node_text)

root_item = Item(
    'xcb',
    {'header', 'extension-xname', 'extension-name', 'major-version', 'minor-version'},
    Many(
        one_of(
            import_item,
            request,
            struct,
            xidtype,
            xidunion,
            typedef,
            enum,
            event,
            eventcopy,
            eventstruct,
            union,
            error,
            errorcopy,
        )
    ),
    cnv=Bindings.make,
)
