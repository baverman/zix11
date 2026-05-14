#!/usr/bin/env python3

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterator

import xcbxml


XML_PATH = Path("/usr/share/xcb/xproto.xml")
OUT_PATH = Path("src/xproto.zig")


@dataclass(frozen=True)
class GeneratorInput:
    path: Path
    bindings: xcbxml.Bindings


class Emit:
    def __init__(self) -> None:
        self.indent = 0
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        if text:
            self.lines.append(("    " * self.indent) + text)
        else:
            self.lines.append("")

    @contextmanager
    def block(self) -> Iterator[None]:
        self.indent += 1
        try:
            yield
        finally:
            self.indent -= 1

    def render(self) -> str:
        return "\n".join(self.lines)


Expr = xcbxml.FieldRef | xcbxml.Op | int


@dataclass(frozen=True)
class ScalarType:
    x_name: str
    zig_name: str
    wire_size: int
    def render_zig(self) -> str:
        return self.zig_name

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return str(self.wire_size)

    def fixed_wire_size(self) -> int | None:
        return self.wire_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        if self.zig_name == "bool":
            emit(f"try writer.writeByte(@intFromBool({value_expr}));")
        elif self.zig_name == "u8":
            emit(f"try writer.writeByte({value_expr});")
        else:
            emit(f"try writer.writeInt({self.zig_name}, {value_expr}, .little);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        if self.zig_name == "bool":
            emit(f"const {target_name} = (try reader.takeByte()) != 0;")
        elif self.zig_name == "u8":
            emit(f"const {target_name} = try reader.takeByte();")
        else:
            emit(f"const {target_name} = try reader.takeInt({self.zig_name}, .little);")


SCALAR_TYPES: dict[str, ScalarType] = {
    "BOOL": ScalarType("BOOL", "bool", 1),
    "BYTE": ScalarType("BYTE", "u8", 1),
    "CARD8": ScalarType("CARD8", "u8", 1),
    "CARD16": ScalarType("CARD16", "u16", 2),
    "CARD32": ScalarType("CARD32", "u32", 4),
    "INT8": ScalarType("INT8", "i8", 1),
    "INT16": ScalarType("INT16", "i16", 2),
    "INT32": ScalarType("INT32", "i32", 4),
    "char": ScalarType("char", "u8", 1),
    "void": ScalarType("void", "u8", 1),
}


@dataclass(frozen=True)
class EnumType:
    name: str
    wire_type: ScalarType
    def render_zig(self) -> str:
        return self.name

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return str(self.wire_type.wire_size)

    def fixed_wire_size(self) -> int | None:
        return self.wire_type.wire_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        tag_type = self.wire_type.zig_name
        if self.wire_type.wire_size == 1:
            emit(f"try writer.writeByte(@intCast(@intFromEnum({value_expr})));")
        else:
            emit(f"try writer.writeInt({tag_type}, @intCast(@intFromEnum({value_expr})), .little);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        tag_type = self.wire_type.zig_name
        if self.wire_type.wire_size == 1:
            emit(f"const {target_name} = @as({self.name}, @enumFromInt(try reader.takeInt({tag_type}, .little)));")
        else:
            emit(f"const {target_name} = @as({self.name}, @enumFromInt(try reader.takeInt({tag_type}, .little)));")


@dataclass(frozen=True)
class MaskType:
    name: str
    wire_type: ScalarType
    def render_zig(self) -> str:
        return self.wire_type.zig_name

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return str(self.wire_type.wire_size)

    def fixed_wire_size(self) -> int | None:
        return self.wire_type.wire_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        self.wire_type.emit_encode(emit, value_expr)

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        self.wire_type.emit_decode(emit, target_name)


@dataclass(frozen=True)
class XidType:
    name: str
    def render_zig(self) -> str:
        return zig_xid_name(self.name)

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return "4"

    def fixed_wire_size(self) -> int | None:
        return 4

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"try writer.writeInt(u32, @intFromEnum({value_expr}), .little);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = @as({zig_xid_name(self.name)}, @enumFromInt(try reader.takeInt(u32, .little)));")


@dataclass(frozen=True)
class XidUnionType:
    name: str
    members: tuple[str, ...]
    def render_zig(self) -> str:
        return zig_xid_name(self.name)

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return "4"

    def fixed_wire_size(self) -> int | None:
        return 4

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"try writer.writeInt(u32, @intFromEnum({value_expr}), .little);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = @as({zig_xid_name(self.name)}, @enumFromInt(try reader.takeInt(u32, .little)));")


@dataclass
class StructType:
    name: str
    decl: StructDecl | None = None

    def render_zig(self) -> str:
        return self.name

    def byte_len_expr(self, value_expr: str) -> str:
        return f"{value_expr}.byteLen()"

    def fixed_wire_size(self) -> int | None:
        return None

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"try {value_expr}.encode(writer);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        if self.is_dynamic:
            emit(f"const {target_name} = try {self.name}.decode(allocator, reader);")
        else:
            emit(f"const {target_name} = try {self.name}.decode(reader);")

    @property
    def is_dynamic(self) -> bool:
        return False if self.decl is None else self.decl.is_dynamic


@dataclass
class UnionType:
    name: str
    decl: UnionDecl | None = None

    def render_zig(self) -> str:
        return self.name

    def byte_len_expr(self, value_expr: str) -> str:
        return f"{value_expr}.byteLen()"

    def fixed_wire_size(self) -> int | None:
        return None if self.decl is None else self.decl.raw_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"try {value_expr}.encode(writer);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = try {self.name}.decode(reader);")


TypeRef = ScalarType | EnumType | MaskType | XidType | XidUnionType | StructType | UnionType


@dataclass
class FieldItem:
    name: str
    type_ref: TypeRef
    altenum: str | None = None
    derived_from: ListItem | MaskListItem | None = None

    def emit_decl(self, emit: Emit) -> None:
        emit(f"{render_field_name(self.name)}: {self.type_ref.render_zig()},")

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = previous_item
        return self.type_ref.byte_len_expr(f"{owner_expr}.{render_field_name(self.name)}")

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = previous_item
        if self.derived_from is not None:
            if isinstance(self.derived_from, ListItem):
                self.type_ref.emit_encode(emit, self.derived_from.derived_len_expr(owner_expr))
                return
            if isinstance(self.derived_from, MaskListItem):
                value_expr = (
                    f"wire.computeValueMask({self.derived_from.require_spec_name()}, "
                    f"{owner_expr}.{render_field_name(self.derived_from.name)})"
                )
                self.type_ref.emit_encode(emit, value_expr)
                return
            raise NotImplementedError(f"derived field encode is not implemented for {self.name}")
            return
        self.type_ref.emit_encode(emit, f"{owner_expr}.{render_field_name(self.name)}")

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = previous_item
        self.type_ref.emit_decode(emit, render_local_name(self.name))


@dataclass(frozen=True)
class PadBytesItem:
    count: int

    def emit_decl(self, emit: Emit) -> None:
        _ = emit

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = owner_expr
        _ = previous_item
        return str(self.count)

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = owner_expr
        _ = previous_item
        emit(f"try writer.splatByteAll(0, {self.count});")

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = previous_item
        emit(f"_ = try reader.take({self.count});")


@dataclass(frozen=True)
class PadAlignItem:
    align: int

    def emit_decl(self, emit: Emit) -> None:
        _ = emit

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        if not isinstance(previous_item, ListItem):
            raise NotImplementedError("pad-align byteLen requires preceding list item")
        if self.align != 4:
            raise NotImplementedError(f"pad-align byteLen only supports align=4, got {self.align}")
        return f"wire.pad4({previous_item.payload_len_expr(owner_expr)})"

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        if not isinstance(previous_item, ListItem):
            raise NotImplementedError("pad-align encode requires preceding list item")
        if self.align != 4:
            raise NotImplementedError(f"pad-align encode only supports align=4, got {self.align}")
        emit(f"try writer.splatByteAll(0, wire.pad4({previous_item.payload_len_expr(owner_expr)}));")

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        if not isinstance(previous_item, ListItem):
            raise NotImplementedError("pad-align decode requires preceding list item")
        if self.align != 4:
            raise NotImplementedError(f"pad-align decode only supports align=4, got {self.align}")
        emit(f"_ = try reader.take(wire.pad4({previous_item.decoded_payload_len_expr()}));")


@dataclass(frozen=True)
class ListItem:
    name: str
    item_type: TypeRef
    len_expr: Expr | None

    def fixed_count(self) -> int | None:
        return self.len_expr if isinstance(self.len_expr, int) else None

    def is_inline_fixed(self) -> bool:
        return self.fixed_count() is not None and self.item_type.fixed_wire_size() is not None

    def emit_decl(self, emit: Emit) -> None:
        rendered = self.item_type.render_zig()
        if self.is_inline_fixed():
            zig_type = f"[{self.fixed_count()}]{rendered}"
        elif isinstance(self.item_type, StructType):
            zig_type = f"[]{rendered}"
        else:
            zig_type = f"[]const {rendered}"
        emit(f"{render_field_name(self.name)}: {zig_type},")

    def payload_len_expr(self, owner_expr: str) -> str:
        value_expr = f"{owner_expr}.{render_field_name(self.name)}"
        fixed_size = self.item_type.fixed_wire_size()
        fixed_count = self.fixed_count()
        if fixed_count is not None and fixed_size is not None:
            if fixed_size == 1:
                return str(fixed_count)
            return f"{fixed_count} * {fixed_size}"
        if fixed_size is not None:
            if fixed_size == 1:
                return f"{value_expr}.len"
            return f"{value_expr}.len * {fixed_size}"
        return f"wire.structListByteLen({value_expr})"

    def decoded_payload_len_expr(self) -> str:
        value_expr = render_field_name(self.name)
        fixed_size = self.item_type.fixed_wire_size()
        fixed_count = self.fixed_count()
        if fixed_count is not None and fixed_size is not None:
            if fixed_size == 1:
                return str(fixed_count)
            return f"{fixed_count} * {fixed_size}"
        if fixed_size is not None:
            if fixed_size == 1:
                return f"{value_expr}.len"
            return f"{value_expr}.len * {fixed_size}"
        return f"wire.structListByteLen({value_expr})"

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = previous_item
        return self.payload_len_expr(owner_expr)

    def derived_len_expr(self, owner_expr: str) -> str:
        value_expr = f"{owner_expr}.{render_field_name(self.name)}"
        fixed_size = self.item_type.fixed_wire_size()
        if fixed_size == 1:
            return f"@intCast({value_expr}.len)"
        return f"@intCast({value_expr}.len)"

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = previous_item
        value_expr = f"{owner_expr}.{render_field_name(self.name)}"
        fixed_size = self.item_type.fixed_wire_size()
        if fixed_size == 1:
            if self.is_inline_fixed():
                emit(f"try writer.writeAll({value_expr}[0..]);")
            else:
                emit(f"try writer.writeAll({value_expr});")
            return
        emit(f"for ({value_expr}) |elem| {{")
        with emit.block():
            self.item_type.emit_encode(emit, "elem")
        emit("}")

    def emit_decode(
        self,
        emit: Emit,
        previous_item: Item | None = None,
        decode_mode: str = "alloc",
    ) -> None:
        _ = previous_item
        field_name = render_local_name(self.name)
        len_expr = None if self.len_expr is None else render_expr(self.len_expr)
        fixed_size = self.item_type.fixed_wire_size()
        fixed_count = self.fixed_count()
        if fixed_count is not None and fixed_size is not None:
            elem_type = self.item_type.render_zig()
            emit(f"var {field_name}: [{fixed_count}]{elem_type} = undefined;")
            if fixed_size == 1:
                emit(f"@memcpy({field_name}[0..], try reader.take({fixed_count}));")
                return
            emit(f"for (&{field_name}) |*elem| {{")
            with emit.block():
                self.item_type.emit_decode(emit, "elem_value")
                emit("elem.* = elem_value;")
            emit("}")
            return
        if fixed_size == 1:
            if len_expr is None:
                raise NotImplementedError(f"list decode without length expression is not implemented for {self.name}")
            emit(f"const {field_name}_byte_len = @as(usize, {len_expr});")
            emit(f"const {field_name}_temp = try reader.take({field_name}_byte_len);")
            if decode_mode == "buf":
                emit(f"if (scratch_used + {field_name}_byte_len > scratch.len) return error.BufferTooSmall;")
                emit(f"@memcpy(scratch[scratch_used..][0..{field_name}_byte_len], {field_name}_temp);")
                emit(f"const {field_name} = scratch[scratch_used..][0..{field_name}_byte_len];")
                emit(f"scratch_used += {field_name}_byte_len;")
            else:
                emit(f"const {field_name} = try allocator.dupe(u8, {field_name}_temp);")
            return
        if len_expr is None:
            raise NotImplementedError(f"struct-list decode without length expression is not implemented for {self.name}")
        elem_type = self.item_type.render_zig()
        emit(f"const {field_name} = try allocator.alloc({elem_type}, @as(usize, {len_expr}));")
        emit(f"errdefer allocator.free({field_name});")
        emit(f"var {field_name}_decoded: usize = 0;")
        is_dynamic_struct = isinstance(self.item_type, StructType) and self.item_type.is_dynamic
        if is_dynamic_struct:
            emit(f"errdefer for ({field_name}[0..{field_name}_decoded]) |*elem| elem.deinit(allocator);")
        emit(f"for ({field_name}) |*elem| {{")
        with emit.block():
            self.item_type.emit_decode(emit, "elem_value")
            emit("elem.* = elem_value;")
            emit(f"{field_name}_decoded += 1;")
        emit("}")


@dataclass(frozen=True)
class MaskCase:
    field_name: str
    enum_name: str
    enum_item: str
    value_type: TypeRef


@dataclass
class MaskListItem:
    name: str
    mask_field_name: str
    cases: tuple[MaskCase, ...]
    type_name: str | None = None
    spec_name: str | None = None

    def set_generated_names(self, request_name: str) -> None:
        suffix = "".join(part[:1].upper() + part[1:] for part in self.name.split("_"))
        self.type_name = f"{request_name}{suffix}"
        self.spec_name = f"{self.type_name}Spec"

    def require_type_name(self) -> str:
        if self.type_name is None:
            raise ValueError(f"mask-list type name was not initialized for {self.name}")
        return self.type_name

    def require_spec_name(self) -> str:
        if self.spec_name is None:
            raise ValueError(f"mask-list spec name was not initialized for {self.name}")
        return self.spec_name

    def emit_decl(self, emit: Emit) -> None:
        emit(f"{render_field_name(self.name)}: {self.require_type_name()},")

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = previous_item
        return f"wire.valueListByteLen({self.require_spec_name()}, {owner_expr}.{render_field_name(self.name)})"

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = previous_item
        emit(
            f"try wire.writeValueList({self.require_spec_name()}, {owner_expr}.{render_field_name(self.name)}, writer);"
        )

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = emit
        _ = previous_item
        raise NotImplementedError(f"mask-list decode emission is not implemented for {self.name}")


Item = FieldItem | PadBytesItem | PadAlignItem | ListItem | MaskListItem


@dataclass
class StructDecl:
    name: str
    items: tuple[Item, ...]

    @cached_property
    def is_dynamic(self) -> bool:
        for item in self.items:
            if isinstance(item, ListItem) and not item.is_inline_fixed():
                return True
            if isinstance(item, FieldItem) and isinstance(item.type_ref, StructType):
                if item.type_ref.is_dynamic:
                    return True
        return False


@dataclass(frozen=True)
class ReplyDecl:
    items: tuple[Item, ...]


@dataclass(frozen=True)
class RequestDecl:
    name: str
    opcode: int
    items: tuple[Item, ...]
    reply: ReplyDecl | None
    combine_adjacent: str | None = None


@dataclass(frozen=True)
class EventDecl:
    name: str
    number: int
    items: tuple[Item, ...]
    no_sequence_number: str | None = None
    xge: str | None = None


@dataclass(frozen=True)
class EnumItemDecl:
    name: str
    value: int


@dataclass(frozen=True)
class EnumDecl:
    name: str
    items: tuple[EnumItemDecl, ...]
    is_mask: bool = False


@dataclass(frozen=True)
class XidDecl:
    name: str


@dataclass(frozen=True)
class XidUnionDecl:
    name: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class UnionDecl:
    name: str
    items: tuple[Item, ...]
    raw_size: int


@dataclass(frozen=True)
class TypedefDecl:
    name: str
    alias: str


@dataclass(frozen=True)
class ModuleIR:
    header: str
    typedefs: dict[str, TypedefDecl]
    xidtypes: dict[str, XidDecl]
    xidunions: dict[str, XidUnionDecl]
    unions: dict[str, UnionDecl]
    core_error_codes: EnumDecl
    enums: dict[str, EnumDecl]
    structs: dict[str, StructDecl]
    requests: dict[str, RequestDecl]
    events: dict[str, EventDecl]


class Resolver:
    def __init__(self, bindings: xcbxml.Bindings) -> None:
        self.bindings = bindings
        self.struct_types: dict[str, StructType] = {}
        self.union_types: dict[str, UnionType] = {}
        self.typedefs = {it.name: TypedefDecl(it.name, it.alias) for it in bindings.typedef}
        self.xidtypes = {it.name: XidDecl(it.name) for it in bindings.xidtype}
        self.xidunions = {
            it.name: XidUnionDecl(it.name, tuple(it.fields))
            for it in bindings.xidunion
        }
        self.mask_enum_names = self.collect_mask_enum_names()
        self.enums = {
            it.name: EnumDecl(
                it.name,
                tuple(EnumItemDecl(field.name, field.value) for field in it.fields),
                is_mask=it.name in self.mask_enum_names,
            )
            for it in bindings.enum
        }
        self.core_error_codes = EnumDecl(
            "Error",
            tuple(
                [EnumItemDecl(it.name, int(it.number)) for it in bindings.error]
                + [EnumItemDecl(it.name, int(it.number)) for it in bindings.errorcopy]
            ),
            is_mask=False,
        )

    def collect_mask_enum_names(self) -> set[str]:
        result: set[str] = set()

        def visit_items(items: Sequence[object]) -> None:
            for item in items:
                if isinstance(item, xcbxml.Field) and item.mask is not None:
                    result.add(item.mask)
                elif isinstance(item, xcbxml.SwitchField):
                    for case in item.items:
                        enum_name, _ = case.enum_ref
                        result.add(enum_name)
                        if case.field.mask is not None:
                            result.add(case.field.mask)

        for struct in self.bindings.struct:
            visit_items(struct.fields)
        for request in self.bindings.request:
            visit_items(request.fields)
            if request.reply is not None:
                visit_items(request.reply.fields)
        for event in self.bindings.event:
            visit_items(event.fields)
        for error in self.bindings.error:
            visit_items(error.fields)
        for union in self.bindings.union:
            visit_items(union.fields)

        return result

    def resolve_module(self) -> ModuleIR:
        structs = {it.name: self.resolve_struct(it) for it in self.bindings.struct}
        for name, struct_decl in structs.items():
            self.struct_types.setdefault(name, StructType(name)).decl = struct_decl
        unions = {it.name: self.resolve_union(it) for it in self.bindings.union}
        for name, union_decl in unions.items():
            self.union_types.setdefault(name, UnionType(name)).decl = union_decl
        requests = {it.name: self.resolve_request(it) for it in self.bindings.request}
        events = {it.name: self.resolve_event(it) for it in self.bindings.event}
        for eventcopy in self.bindings.eventcopy:
            event_src = events[eventcopy.ref]
            events[eventcopy.name] = EventDecl(
                name=eventcopy.name,
                number=int(eventcopy.number),
                items=event_src.items,
                no_sequence_number=event_src.no_sequence_number,
                xge=event_src.xge,
            )
        return ModuleIR(
            header=self.bindings.header,
            typedefs=self.typedefs,
            xidtypes=self.xidtypes,
            xidunions=self.xidunions,
            unions=unions,
            core_error_codes=self.core_error_codes,
            enums=self.enums,
            structs=structs,
            requests=requests,
            events=events,
        )

    def resolve_typename(self, x_name: str) -> str:
        seen: set[str] = set()
        current = x_name
        while current in self.typedefs:
            if current in seen:
                raise ValueError(f"cyclic typedef: {x_name}")
            seen.add(current)
            current = self.typedefs[current].alias
        return current

    def resolve_wire_scalar(self, x_name: str) -> ScalarType:
        resolved = self.resolve_typename(x_name)
        if resolved not in SCALAR_TYPES:
            raise ValueError(f"not a scalar type: {x_name}")
        return SCALAR_TYPES[resolved]

    def resolve_type(self, x_name: str, *, enum_name: str | None = None, mask_name: str | None = None) -> TypeRef:
        if enum_name is not None:
            return EnumType(enum_name, self.resolve_wire_scalar(x_name))
        if mask_name is not None:
            return MaskType(mask_name, self.resolve_wire_scalar(x_name))

        resolved = self.resolve_typename(x_name)
        if resolved in SCALAR_TYPES:
            return SCALAR_TYPES[resolved]
        if resolved in self.xidtypes:
            return XidType(resolved)
        if resolved in self.xidunions:
            return XidUnionType(resolved, self.xidunions[resolved].members)
        if resolved in {it.name for it in self.bindings.union}:
            return self.union_types.setdefault(resolved, UnionType(resolved))
        return self.struct_types.setdefault(resolved, StructType(resolved))

    def resolve_field(self, field: xcbxml.Field) -> FieldItem:
        return FieldItem(
            name=field.name,
            type_ref=self.resolve_type(field.type, enum_name=field.enum, mask_name=field.mask),
            altenum=field.altenum,
        )

    def resolve_mask_case(self, item: xcbxml.SwitchItem) -> MaskCase:
        enum_name, enum_item = item.enum_ref
        return MaskCase(
            field_name=item.field.name,
            enum_name=enum_name,
            enum_item=enum_item,
            value_type=self.resolve_type(
                item.field.type,
                enum_name=item.field.enum,
                mask_name=item.field.mask,
            ),
        )

    def resolve_item(self, item: object) -> Item:
        if isinstance(item, xcbxml.Field):
            return self.resolve_field(item)
        if isinstance(item, xcbxml.Pad):
            if item.count is not None:
                return PadBytesItem(item.count)
            assert item.align is not None
            return PadAlignItem(int(item.align))
        if isinstance(item, xcbxml.ListField):
            return ListItem(
                name=item.name,
                item_type=self.resolve_type(item.item_type),
                len_expr=item.len_expr,
            )
        if isinstance(item, xcbxml.SwitchField):
            return MaskListItem(
                name=item.name,
                mask_field_name=item.fieldref.ref,
                cases=tuple(self.resolve_mask_case(case) for case in item.items),
            )
        raise TypeError(f"unsupported item: {item!r}")

    def resolve_items(self, items: Sequence[object]) -> tuple[Item, ...]:
        return tuple(self.resolve_item(item) for item in items)

    def resolve_reply(self, reply: xcbxml.Reply | None) -> ReplyDecl | None:
        if reply is None:
            return None
        items = self.resolve_items(reply.fields)
        self.mark_derived_fields(items)
        return ReplyDecl(items=items)

    def mark_derived_fields(self, items: tuple[Item, ...]) -> None:
        fields = {
            item.name: item
            for item in items
            if isinstance(item, FieldItem)
        }
        for item in items:
            if isinstance(item, ListItem) and isinstance(item.len_expr, xcbxml.FieldRef):
                if item.len_expr.ref in fields:
                    fields[item.len_expr.ref].derived_from = item
            elif isinstance(item, MaskListItem):
                if item.mask_field_name in fields:
                    fields[item.mask_field_name].derived_from = item

    def resolve_struct(self, struct: xcbxml.Struct) -> StructDecl:
        items = self.resolve_items(struct.fields)
        self.mark_derived_fields(items)
        return StructDecl(name=struct.name, items=items)

    def union_item_size(self, item: Item) -> int:
        if isinstance(item, FieldItem):
            size = item.type_ref.fixed_wire_size()
            if size is None:
                raise NotImplementedError(f"union field must be fixed-size: {item.name}")
            return size
        if isinstance(item, PadBytesItem):
            return item.count
        if isinstance(item, ListItem):
            fixed_size = item.item_type.fixed_wire_size()
            fixed_count = item.fixed_count()
            if fixed_size is None or fixed_count is None:
                raise NotImplementedError(f"union list must be fixed-size: {item.name}")
            return fixed_size * fixed_count
        raise NotImplementedError(f"unsupported union item: {item!r}")

    def resolve_union(self, union: xcbxml.Union) -> UnionDecl:
        items = self.resolve_items(union.fields)
        raw_size = max(self.union_item_size(item) for item in items)
        return UnionDecl(name=union.name, items=items, raw_size=raw_size)

    def resolve_request(self, request: xcbxml.Request) -> RequestDecl:
        items = self.resolve_items(request.fields)
        self.mark_derived_fields(items)
        for item in items:
            if isinstance(item, MaskListItem):
                item.set_generated_names(request.name)
        return RequestDecl(
            name=request.name,
            opcode=int(request.opcode),
            items=items,
            reply=self.resolve_reply(request.reply),
            combine_adjacent=request.combine_adjacent,
        )

    def resolve_event(self, event: xcbxml.Event) -> EventDecl:
        return EventDecl(
            name=event.name,
            number=int(event.number),
            items=self.resolve_items(event.fields),
            no_sequence_number=event.no_sequence_number,
            xge=event.xge,
        )

def zig_xid_name(name: str) -> str:
    return name.title().replace("_", "")


def zig_enum_item_name(name: str) -> str:
    if name and name[0].isdigit():
        return f'@"{name}"'
    if not name:
        return name
    parts = name.replace("-", "_").split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def emit_prelude(emit: Emit) -> None:
    emit("// zig fmt: off")
    emit("// This file is generated by tools/gennew.py")
    emit()
    emit('const std = @import("std");')
    emit('const wire = @import("wire.zig");')
    emit('const errors = @import("errors.zig");')
    emit("const EncodeError = errors.EncodeError;")
    emit("const DecodeError = errors.DecodeError;")
    emit("const AllocDecodeError = errors.AllocDecodeError;")
    emit("const BufferDecodeError = errors.BufferDecodeError;")
    emit()


def emit_xid_decl(emit: Emit, decl: XidDecl | XidUnionDecl) -> None:
    emit(f"pub const {zig_xid_name(decl.name)} = enum(u32) {{ _ }};")
    emit()


def emit_union_decl(emit: Emit, decl: UnionDecl) -> None:
    emit(f"pub const {decl.name} = struct {{")
    with emit.block():
        emit(f"raw: [{decl.raw_size}]u8,")
        emit()
        emit("pub fn byteLen(self: @This()) usize {")
        with emit.block():
            emit("_ = self;")
            emit(f"return {decl.raw_size};")
        emit("}")
        emit()
        emit("pub fn encode(self: @This(), writer: *std.Io.Writer) EncodeError!void {")
        with emit.block():
            emit("try writer.writeAll(self.raw[0..]);")
        emit("}")
        emit()
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            emit(f"var raw: [{decl.raw_size}]u8 = undefined;")
            emit(f"@memcpy(raw[0..], try reader.take({decl.raw_size}));")
            emit("return .{ .raw = raw };")
        emit("}")
    emit("};")
    emit()


def render_field_name(name: str) -> str:
    return name


def render_local_name(name: str) -> str:
    if name == "type":
        return '@"type"'
    return name


def render_expr(expr: Expr) -> str:
    if isinstance(expr, int):
        return str(expr)
    if isinstance(expr, xcbxml.FieldRef):
        return render_field_name(expr.ref)
    if isinstance(expr, xcbxml.Op):
        op = {
            "+": "+",
            "-": "-",
            "*": "*",
            "/": "/",
        }.get(expr.op)
        if op is None:
            raise NotImplementedError(f"unsupported expression operator: {expr.op}")
        return f"({render_expr(expr.left)} {op} {render_expr(expr.right)})"
    raise TypeError(f"unsupported expression: {expr!r}")


def expr_uses_fieldref(expr: Expr | None, name: str) -> bool:
    if expr is None:
        return False
    if isinstance(expr, int):
        return False
    if isinstance(expr, xcbxml.FieldRef):
        return expr.ref == name
    if isinstance(expr, xcbxml.Op):
        return expr_uses_fieldref(expr.left, name) or expr_uses_fieldref(expr.right, name)
    raise TypeError(f"unsupported expression: {expr!r}")


def item_uses_fieldref(item: Item, name: str) -> bool:
    if isinstance(item, ListItem):
        return expr_uses_fieldref(item.len_expr, name)
    return False


def reply_name(request_name: str) -> str:
    return f"{request_name}Reply"


def request_decl_name(request_name: str) -> str:
    if request_name == "Setup":
        return "SetupRequest"
    return request_name

def header_item(items: tuple[Item, ...]) -> Item | None:
    if not items:
        return None
    first = items[0]
    if isinstance(first, FieldItem) and first.type_ref.fixed_wire_size() == 1:
        return first
    if isinstance(first, PadBytesItem) and first.count == 1:
        return first
    return None


def body_items(items: tuple[Item, ...]) -> tuple[Item, ...]:
    return items[1:] if header_item(items) is not None else items


def reply_decode_mode(decl: StructDecl) -> str:
    for item in decl.items:
        if isinstance(item, ListItem):
            if item.is_inline_fixed():
                continue
            if item.item_type.fixed_wire_size() != 1:
                return "alloc"
        elif isinstance(item, FieldItem) and isinstance(item.type_ref, StructType):
            if item.type_ref.is_dynamic:
                return "alloc"
    return "buf"


def emit_enum_decl(emit: Emit, decl: EnumDecl) -> None:
    seen_values: dict[int, str] = {}
    aliases: list[tuple[str, str]] = []

    emit(f"pub const {decl.name} = enum(u32) {{")
    with emit.block():
        for item in decl.items:
            item_name = zig_enum_item_name(item.name)
            previous_name = seen_values.get(item.value)
            if previous_name is None:
                emit(f"{item_name} = {item.value},")
                seen_values[item.value] = item_name
            else:
                aliases.append((item_name, previous_name))
        emit("_,")
        if decl.is_mask:
            emit()
            emit("pub fn of(flags: []const @This()) u32 {")
            with emit.block():
                emit("return wire.maskOf(@This(), flags);")
            emit("}")
        if aliases:
            emit()
            for alias_name, target_name in aliases:
                emit(f"pub const {alias_name} = @This().{target_name};")
    emit("};")
    emit()


def emit_payload_decl_fields(emit: Emit, items: tuple[Item, ...]) -> None:
    for item in items:
        if isinstance(item, FieldItem) and item.derived_from is not None:
            continue
        item.emit_decl(emit)


def payload_byte_len_expr(items: tuple[Item, ...], owner_expr: str) -> str:
    terms: list[str] = []
    previous_item: Item | None = None
    for item in items:
        terms.append(item.byte_len_term(owner_expr, previous_item))
        previous_item = item
    return " + ".join(terms) if terms else "0"


def emit_payload_byte_len(emit: Emit, items: tuple[Item, ...], owner_expr: str) -> None:
    expr = payload_byte_len_expr(items, owner_expr)
    emit(f"return {expr};")


def emit_struct_byte_len(emit: Emit, decl: StructDecl) -> None:
    emit("pub fn byteLen(self: @This()) usize {")
    with emit.block():
        expr = payload_byte_len_expr(decl.items, "self")
        if "self" not in expr:
            emit("_ = self;")
        emit(f"return {expr};")
    emit("}")
    emit()


def emit_payload_encode_body(
    emit: Emit,
    items: tuple[Item, ...],
    owner_expr: str,
    previous_item: Item | None = None,
) -> None:
    current_previous = previous_item
    for item in items:
        item.emit_encode(emit, owner_expr, current_previous)
        current_previous = item


def emit_struct_encode(emit: Emit, decl: StructDecl) -> None:
    emit("pub fn encode(self: @This(), writer: *std.Io.Writer) EncodeError!void {")
    with emit.block():
        emit_payload_encode_body(emit, decl.items, "self")
    emit("}")
    emit()


def emit_struct_decode_signature(emit: Emit, decl: StructDecl) -> None:
    if decl.is_dynamic:
        emit("pub fn decode(allocator: std.mem.Allocator, reader: *std.Io.Reader) AllocDecodeError!@This() {")
    else:
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")


def emit_payload_decode_body(
    emit: Emit,
    items: tuple[Item, ...],
    previous_item: Item | None = None,
    decode_mode: str = "alloc",
) -> None:
    current_previous = previous_item
    for item in items:
        if isinstance(item, ListItem):
            item.emit_decode(emit, current_previous, decode_mode)
        else:
            item.emit_decode(emit, current_previous)
        current_previous = item


def emit_payload_decode_return(emit: Emit, items: tuple[Item, ...]) -> None:
    emit("return .{")
    with emit.block():
        for item in items:
            if isinstance(item, FieldItem) and item.derived_from is not None:
                continue
            if isinstance(item, FieldItem | ListItem):
                emit(f".{render_field_name(item.name)} = {render_local_name(item.name)},")
    emit("};")


def emit_struct_decode(emit: Emit, decl: StructDecl) -> None:
    emit_struct_decode_signature(emit, decl)
    with emit.block():
        emit_payload_decode_body(emit, decl.items, decode_mode="alloc")
        emit_payload_decode_return(emit, decl.items)
    emit("}")
    emit()


def emit_struct_deinit(emit: Emit, decl: StructDecl) -> None:
    if not decl.is_dynamic:
        return
    emit("pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {")
    with emit.block():
        for item in decl.items:
            if isinstance(item, ListItem) and not item.is_inline_fixed():
                field_name = render_field_name(item.name)
                if isinstance(item.item_type, StructType) and item.item_type.is_dynamic:
                    emit(f"for (self.{field_name}) |*elem| elem.deinit(allocator);")
                emit(f"allocator.free(self.{field_name});")
    emit("}")
    emit()


def emit_struct_decl(emit: Emit, decl: StructDecl) -> None:
    emit(f"pub const {decl.name} = struct {{")
    with emit.block():
        emit_payload_decl_fields(emit, decl.items)
        emit()
        emit_struct_byte_len(emit, decl)
        emit_struct_encode(emit, decl)
        emit_struct_decode(emit, decl)
        emit_struct_deinit(emit, decl)
    emit("};")
    emit()


def emit_reply_decl(emit: Emit, request: RequestDecl) -> None:
    assert request.reply is not None
    items = request.reply.items
    header = header_item(items)
    body = body_items(items)
    decl = StructDecl(name=reply_name(request.name), items=items)
    decode_mode = "fixed" if not decl.is_dynamic else reply_decode_mode(decl)
    uses_reply_length = any(item_uses_fieldref(item, "length") for item in body)

    emit(f"pub const {reply_name(request.name)} = struct {{")
    with emit.block():
        emit_payload_decl_fields(emit, items)
        emit()
        emit_struct_byte_len(emit, decl)
        emit_struct_encode(emit, decl)
        if decode_mode == "alloc":
            emit("pub fn decode(allocator: std.mem.Allocator, reader: *std.Io.Reader) AllocDecodeError!@This() {")
        elif decode_mode == "buf":
            emit("pub fn decode(scratch: []u8, reader: *std.Io.Reader) BufferDecodeError!@This() {")
        else:
            emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            emit("_ = try reader.takeByte();")
            if isinstance(header, FieldItem):
                header.emit_decode(emit)
            elif isinstance(header, PadBytesItem):
                header.emit_decode(emit)
            else:
                emit("_ = try reader.take(1);")
            emit("_ = try reader.takeInt(u16, .little);")
            if uses_reply_length:
                emit("const length = try reader.takeInt(u32, .little);")
            else:
                emit("_ = try reader.takeInt(u32, .little);")
            if decode_mode == "buf":
                emit("var scratch_used: usize = 0;")
            emit_payload_decode_body(emit, body, header, decode_mode)
            emit_payload_decode_return(emit, items)
        emit("}")
        emit()
        if decode_mode == "alloc":
            emit_struct_deinit(emit, decl)
    emit("};")
    emit()


def emit_mask_list_decl(emit: Emit, item: MaskListItem) -> None:
    emit(f"pub const {item.require_type_name()} = struct {{")
    with emit.block():
        for case in item.cases:
            emit(f"{render_field_name(case.field_name)}: ?{case.value_type.render_zig()} = null,")
    emit("};")
    emit()

    emit(f"pub const {item.require_spec_name()} = struct {{")
    with emit.block():
        emit("pub const fields = .{")
        with emit.block():
            for case in item.cases:
                emit(
                    f'.{{ .name = "{render_field_name(case.field_name)}", '
                    f'.bit = @intFromEnum({case.enum_name}.{zig_enum_item_name(case.enum_item)}), '
                    f".value_type = {case.value_type.render_zig()} }},"
                )
        emit("};")
    emit("};")
    emit()


def emit_request_aux_decls(emit: Emit, request: RequestDecl) -> None:
    for item in request.items:
        if isinstance(item, MaskListItem):
            emit_mask_list_decl(emit, item)


def emit_request_byte_len(emit: Emit, request: RequestDecl) -> None:
    emit("pub fn byteLen(self: @This()) usize {")
    with emit.block():
        expr = f"4 + {payload_byte_len_expr(body_items(request.items), 'self')}"
        if "self" not in expr:
            emit("_ = self;")
        emit(f"return {expr};")
    emit("}")
    emit()


def emit_request_encode(emit: Emit, request: RequestDecl) -> None:
    emit("pub fn encode(self: @This(), writer: *std.Io.Writer) EncodeError!void {")
    with emit.block():
        emit("const len = self.byteLen();")
        emit("const pad = wire.pad4(len);")
        emit(f"try writer.writeByte(opcode);")
        first = header_item(request.items)
        if isinstance(first, FieldItem):
            first.emit_encode(emit, "self")
        elif isinstance(first, PadBytesItem):
            emit("try writer.splatByteAll(0, 1);")
        else:
            emit("try writer.splatByteAll(0, 1);")
        emit("try writer.writeInt(u16, @intCast((len + pad) / 4), .little);")
        emit_payload_encode_body(emit, body_items(request.items), "self", first)
        emit("try writer.splatByteAll(0, pad);")
    emit("}")
    emit()


def emit_request_decl(emit: Emit, request: RequestDecl) -> None:
    emit_request_aux_decls(emit, request)
    emit(f"pub const {request_decl_name(request.name)} = struct {{")
    with emit.block():
        emit(f"pub const opcode: u8 = {request.opcode};")
        if request.reply is None:
            emit("pub const Reply = void;")
        else:
            emit(f"pub const Reply = {reply_name(request.name)};")
        emit()
        emit_payload_decl_fields(emit, request.items)
        emit()
        emit_request_byte_len(emit, request)
        emit_request_encode(emit, request)
    emit("};")
    emit()


def event_struct_name(name: str) -> str:
    return f"{name}Event"


def event_tag_name(name: str) -> str:
    return name


def emit_event_decl(emit: Emit, decl: EventDecl) -> None:
    emit(f"pub const {event_struct_name(decl.name)} = struct {{")
    with emit.block():
        if decl.xge == "true":
            emit("extension: u8,")
            emit("length: u32,")
            emit("event_type: u16,")
            emit("full_sequence: u32,")
        else:
            emit_payload_decl_fields(emit, decl.items)
        emit()
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            emit("_ = try reader.takeByte();")
            if decl.xge == "true":
                emit("const extension = try reader.takeByte();")
                emit("_ = try reader.takeInt(u16, .little);")
                emit("const length = try reader.takeInt(u32, .little);")
                emit("const event_type = try reader.takeInt(u16, .little);")
                emit("_ = try reader.take(2);")
                emit("const full_sequence = try reader.takeInt(u32, .little);")
                emit("_ = try reader.take(16);")
                emit("_ = try reader.take(@as(usize, length) * 4);")
                emit("return .{")
                with emit.block():
                    emit(".extension = extension,")
                    emit(".length = length,")
                    emit(".event_type = event_type,")
                    emit(".full_sequence = full_sequence,")
                emit("};")
            elif decl.no_sequence_number == "true":
                emit_payload_decode_body(emit, decl.items)
                emit_payload_decode_return(emit, decl.items)
            else:
                header = header_item(decl.items)
                body = body_items(decl.items)
                if isinstance(header, FieldItem):
                    header.emit_decode(emit)
                elif isinstance(header, PadBytesItem):
                    header.emit_decode(emit)
                else:
                    emit("_ = try reader.take(1);")
                emit("_ = try reader.takeInt(u16, .little);")
                emit_payload_decode_body(emit, body, header)
                emit_payload_decode_return(emit, decl.items)
        emit("}")
    emit("};")
    emit()


def emit_event_union(emit: Emit, events: dict[str, EventDecl]) -> None:
    emit("pub const UnknownEvent = struct {")
    with emit.block():
        emit("code: u8,")
        emit("sequence: u16,")
        emit("raw: [32]u8,")
    emit("};")
    emit()

    emit("pub const Event = union(enum) {")
    with emit.block():
        emit("unknown: UnknownEvent,")
        for name in sorted(events, key=lambda n: events[n].number):
            emit(f"{event_tag_name(name)}: {event_struct_name(name)},")
    emit("};")
    emit()


def emit_decode_event(emit: Emit, events: dict[str, EventDecl]) -> None:
    emit("pub fn decodeEvent(reader: *std.Io.Reader) DecodeError!Event {")
    with emit.block():
        emit("const code = (try reader.peek(1))[0] & 0x7f;")
        emit("return switch (code) {")
        with emit.block():
            for name in sorted(events, key=lambda n: events[n].number):
                decl = events[name]
                emit(
                    f'{decl.number} => .{{ .{event_tag_name(name)} = try {event_struct_name(name)}.decode(reader) }},'
                )
            emit("else => blk: {")
            with emit.block():
                emit("const packet = try reader.take(32);")
                emit("var raw: [32]u8 = undefined;")
                emit("@memcpy(raw[0..], packet);")
                emit("break :blk .{ .unknown = .{")
                with emit.block():
                    emit(".code = packet[0] & 0x7f,")
                    emit(".sequence = std.mem.readInt(u16, packet[2..4], .little),")
                    emit(".raw = raw,")
                emit("} };")
            emit("},")
        emit("};")
    emit("}")
    emit()


def render_module(module: ModuleIR) -> str:
    emit = Emit()
    emit_prelude(emit)

    for name in sorted(module.xidtypes):
        emit_xid_decl(emit, module.xidtypes[name])
    for name in sorted(module.xidunions):
        emit_xid_decl(emit, module.xidunions[name])
    for name in sorted(module.unions):
        emit_union_decl(emit, module.unions[name])
    emit_enum_decl(emit, module.core_error_codes)
    conflicting_enum_names = {zig_xid_name(name) for name in module.xidtypes} | {
        zig_xid_name(name) for name in module.xidunions
    }
    for name in sorted(module.enums):
        if name in conflicting_enum_names:
            continue
        emit_enum_decl(emit, module.enums[name])
    for name in sorted(module.structs):
        emit_struct_decl(emit, module.structs[name])
    for name in sorted(module.requests):
        request = module.requests[name]
        if request.reply is not None:
            emit_reply_decl(emit, request)
        emit_request_decl(emit, request)
    for name in sorted(module.events, key=lambda n: module.events[n].number):
        emit_event_decl(emit, module.events[name])
    emit_event_union(emit, module.events)
    emit_decode_event(emit, module.events)

    return emit.render()


def load_bindings(path: Path = XML_PATH) -> GeneratorInput:
    root = ET.parse(path).getroot()
    bindings = xcbxml.root_item.match(root)
    assert isinstance(bindings, xcbxml.Bindings)
    return GeneratorInput(path=path, bindings=bindings)


def main() -> None:
    gen_input = load_bindings()
    bindings = gen_input.bindings
    module = Resolver(bindings).resolve_module()
    OUT_PATH.write_text(render_module(module) + "\n")
    print(
        "generated"
        f" file={OUT_PATH}"
        f" requests={len(module.requests)}"
        f" structs={len(module.structs)}"
        f" xids={len(module.xidtypes) + len(module.xidunions)}"
        f" enums={len(module.enums)}"
    )


if __name__ == "__main__":
    main()
