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


XML_DIR = Path("/usr/share/xcb")
XML_PATHS = (
    XML_DIR / "xproto.xml",
    XML_DIR / "dpms.xml",
    XML_DIR / "render.xml",
    XML_DIR / "randr.xml",
    XML_DIR / "shm.xml",
    XML_DIR / "shape.xml",
    XML_DIR / "xfixes.xml",
    XML_DIR / "xinput.xml",
)
OUT_DIR = Path("src/gen")


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


Expr = xcbxml.FieldRef | xcbxml.ParamRef | xcbxml.Op | xcbxml.SumOf | xcbxml.PopCount | xcbxml.ListElementRef | int


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
            emit(f"writer.writeByte(@intFromBool({value_expr}));")
        elif self.zig_name == "u8":
            emit(f"writer.writeByte({value_expr});")
        else:
            emit(f"writer.writeInt({self.zig_name}, {value_expr});")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        if self.zig_name == "bool":
            emit(f"const {target_name} = (try reader.takeByte()) != 0;")
        elif self.zig_name == "u8":
            emit(f"const {target_name} = try reader.takeByte();")
        else:
            emit(f"const {target_name} = try reader.takeInt({self.zig_name}, .native);")


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
    module_name: str | None = None
    def render_zig(self) -> str:
        return self.name if self.module_name is None else f"{self.module_name}.{self.name}"

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return str(self.wire_type.wire_size)

    def fixed_wire_size(self) -> int | None:
        return self.wire_type.wire_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        tag_type = self.wire_type.zig_name
        if self.wire_type.wire_size == 1:
            emit(f"writer.writeByte(@intCast(@intFromEnum({value_expr})));")
        else:
            emit(f"writer.writeInt({tag_type}, @intCast(@intFromEnum({value_expr})));")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        tag_type = self.wire_type.zig_name
        if self.wire_type.wire_size == 1:
            emit(f"const {target_name} = @as({self.render_zig()}, @enumFromInt(try reader.takeInt({tag_type}, .native)));")
        else:
            emit(f"const {target_name} = @as({self.render_zig()}, @enumFromInt(try reader.takeInt({tag_type}, .native)));")


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
    module_name: str | None = None
    def render_zig(self) -> str:
        type_name = zig_xid_name(self.name)
        return type_name if self.module_name is None else f"{self.module_name}.{type_name}"

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return "4"

    def fixed_wire_size(self) -> int | None:
        return 4

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"writer.writeInt(u32, @intFromEnum({value_expr}));")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = @as({self.render_zig()}, @enumFromInt(try reader.takeInt(u32, .native)));")


@dataclass(frozen=True)
class XidUnionType:
    name: str
    members: tuple[str, ...]
    module_name: str | None = None
    def render_zig(self) -> str:
        type_name = zig_xid_name(self.name)
        return type_name if self.module_name is None else f"{self.module_name}.{type_name}"

    def byte_len_expr(self, value_expr: str) -> str:
        _ = value_expr
        return "4"

    def fixed_wire_size(self) -> int | None:
        return 4

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"{value_expr}.encode(writer);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = try {self.render_zig()}.decode(reader);")


@dataclass
class StructType:
    name: str
    decl: StructDecl | None = None
    module_name: str | None = None

    def render_zig(self) -> str:
        return self.name if self.module_name is None else f"{self.module_name}.{self.name}"

    def byte_len_expr(self, value_expr: str) -> str:
        fixed = self.fixed_wire_size()
        if fixed is not None:
            return str(fixed)
        return f"(blk: {{ var writer = zio.CountingWriter.init(); {value_expr}.encode(&writer); break :blk writer.seek; }})"

    def fixed_wire_size(self) -> int | None:
        return None if self.decl is None else self.decl.fixed_wire_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"{value_expr}.encode(writer);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        params = ""
        if self.decl is not None and self.decl.context_params:
            params = ", " + ", ".join(render_local_name(name) for name in self.decl.context_params)
        if self.is_dynamic:
            emit(f"const {target_name} = try {self.render_zig()}.decode(allocator{params}, reader);")
        else:
            emit(f"const {target_name} = try {self.render_zig()}.decode({params[2:] + ', ' if params else ''}reader);")

    @property
    def is_dynamic(self) -> bool:
        return False if self.decl is None else self.decl.is_dynamic


@dataclass
class UnionType:
    name: str
    decl: UnionDecl | None = None
    module_name: str | None = None

    def render_zig(self) -> str:
        return self.name if self.module_name is None else f"{self.module_name}.{self.name}"

    def byte_len_expr(self, value_expr: str) -> str:
        fixed = self.fixed_wire_size()
        if fixed is not None:
            return str(fixed)
        return f"(blk: {{ var writer = zio.CountingWriter.init(); {value_expr}.encode(&writer); break :blk writer.seek; }})"

    def fixed_wire_size(self) -> int | None:
        return None if self.decl is None else self.decl.raw_size

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f"{value_expr}.encode(writer);")

    def emit_decode(self, emit: Emit, target_name: str) -> None:
        emit(f"const {target_name} = try {self.render_zig()}.decode(reader);")


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
        emit(f"writer.splatByte(0, {self.count});")

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
        if previous_item.item_type.fixed_wire_size() is None:
            emit(f"writer.splatByte(0, wire.pad4(writer.seek - {list_pad_seek_name(previous_item)}));")
        else:
            emit(f"writer.splatByte(0, wire.pad4({previous_item.payload_len_expr(owner_expr)}));")

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        if not isinstance(previous_item, ListItem):
            raise NotImplementedError("pad-align decode requires preceding list item")
        if self.align != 4:
            raise NotImplementedError(f"pad-align decode only supports align=4, got {self.align}")
        if previous_item.item_type.fixed_wire_size() is None:
            emit(f"_ = try reader.take(wire.pad4(reader.seek - {list_pad_seek_name(previous_item)}));")
        else:
            emit(f"_ = try reader.take(wire.pad4({previous_item.decoded_payload_len_expr()}));")


@dataclass(frozen=True)
class RequiredStartAlignItem:
    align: int
    offset: int

    def emit_decl(self, emit: Emit) -> None:
        _ = emit

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = owner_expr
        _ = previous_item
        return "0"

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = emit
        _ = owner_expr
        _ = previous_item
        _ = emit

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = emit
        _ = previous_item
        _ = emit


@dataclass(frozen=True)
class ListItem:
    name: str
    item_type: TypeRef
    len_expr: Expr | None

    def fixed_count(self) -> int | None:
        return self.len_expr if isinstance(self.len_expr, int) else None

    def is_inline_fixed(self) -> bool:
        return self.fixed_count() is not None and self.item_type.fixed_wire_size() is not None

    def emit_decl(self, emit: Emit, *, const_struct_list: bool = False) -> None:
        rendered = self.item_type.render_zig()
        if self.is_inline_fixed():
            zig_type = f"[{self.fixed_count()}]{rendered}"
        elif isinstance(self.item_type, StructType) and not const_struct_list:
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
                emit(f"writer.write({value_expr}[0..]);")
            else:
                emit(f"writer.write({value_expr});")
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


@dataclass(frozen=True)
class SwitchCaseDecl:
    enum_name: str
    enum_item: str
    items: tuple[Item, ...]
    name: str | None = None


@dataclass
class SwitchCaseItem:
    name: str
    fieldref_name: str
    cases: tuple[SwitchCaseDecl, ...]
    align: tuple[tuple[int, int], ...]
    type_name: str | None = None

    def set_generated_name(self, prefix: str) -> None:
        suffix = "".join(part[:1].upper() + part[1:] for part in self.name.split("_"))
        self.type_name = f"{prefix}{suffix}"

    def require_type_name(self) -> str:
        if self.type_name is None:
            raise ValueError(f"switch/case type name was not initialized for {self.name}")
        return self.type_name

    @cached_property
    def context_params(self) -> tuple[str, ...]:
        names: list[str] = []

        def add(name: str) -> None:
            if name not in names:
                names.append(name)

        for case in self.cases:
            local_names: set[str] = set()
            for case_item in case.items:
                if isinstance(case_item, ListItem):
                    for name in expr_fieldrefs(case_item.len_expr):
                        if name != self.fieldref_name and name not in local_names:
                            add(name)
                    for name in expr_paramrefs(case_item.len_expr):
                        add(name)
                elif isinstance(case_item, FieldItem) and isinstance(case_item.type_ref, StructType):
                    if case_item.type_ref.decl is not None:
                        for name in case_item.type_ref.decl.context_params:
                            add(name)
                elif isinstance(case_item, SwitchCaseItem):
                    for name in case_item.context_params:
                        add(name)
                if isinstance(case_item, FieldItem | ListItem | SwitchCaseItem):
                    local_names.add(case_item.name)
        return tuple(names)

    def emit_decl(self, emit: Emit) -> None:
        emit(f"{render_field_name(self.name)}: {self.require_type_name()},")

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = owner_expr
        _ = previous_item
        return (
            f"(blk: {{ var writer = zio.CountingWriter.init(); "
            f"{owner_expr}.{render_field_name(self.name)}.encode(&writer); "
            f"break :blk writer.seek; }})"
        )

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = owner_expr
        _ = previous_item
        emit(f"{owner_expr}.{render_field_name(self.name)}.encode(writer);")

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = previous_item
        params = "".join(f"{render_local_name(name)}, " for name in self.context_params)
        emit(
            f"const {render_local_name(self.name)} = "
            f"try {self.require_type_name()}.decode("
            f"allocator, {render_local_name(self.fieldref_name)}, {params}reader);"
        )


@dataclass
class MaskListItem:
    name: str
    mask_field_name: str
    cases: tuple[MaskCase, ...]
    type_name: str | None = None
    spec_name: str | None = None
    mask_type: str | None = None

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

    def require_mask_type(self) -> str:
        if self.mask_type is None:
            raise ValueError(f"mask-list mask type was not initialized for {self.name}")
        return self.mask_type

    def emit_decl(self, emit: Emit) -> None:
        emit(f"{render_field_name(self.name)}: {self.require_type_name()},")

    def byte_len_term(self, owner_expr: str, previous_item: Item | None = None) -> str:
        _ = previous_item
        return f"wire.valueListByteLen({self.require_spec_name()}, {owner_expr}.{render_field_name(self.name)})"

    def emit_encode(self, emit: Emit, owner_expr: str, previous_item: Item | None = None) -> None:
        _ = previous_item
        emit(
            f"wire.writeValueList({self.require_spec_name()}, {owner_expr}.{render_field_name(self.name)}, writer);"
        )

    def emit_decode(self, emit: Emit, previous_item: Item | None = None) -> None:
        _ = emit
        _ = previous_item
        raise NotImplementedError(f"mask-list decode emission is not implemented for {self.name}")


Item = (
    FieldItem
    | PadBytesItem
    | PadAlignItem
    | RequiredStartAlignItem
    | ListItem
    | MaskListItem
    | SwitchCaseItem
)


@dataclass
class StructDecl:
    name: str
    items: tuple[Item, ...]

    @cached_property
    def is_dynamic(self) -> bool:
        for item in self.items:
            if isinstance(item, ListItem) and not item.is_inline_fixed():
                return True
            if isinstance(item, SwitchCaseItem):
                return True
            if isinstance(item, FieldItem) and isinstance(item.type_ref, StructType):
                if item.type_ref.is_dynamic:
                    return True
        return False

    @cached_property
    def fixed_wire_size(self) -> int | None:
        total = 0
        for item in self.items:
            if isinstance(item, FieldItem):
                size = item.type_ref.fixed_wire_size()
                if size is None:
                    return None
                total += size
                continue
            if isinstance(item, PadBytesItem):
                total += item.count
                continue
            if isinstance(item, ListItem):
                fixed_size = item.item_type.fixed_wire_size()
                fixed_count = item.fixed_count()
                if fixed_size is None or fixed_count is None:
                    return None
                total += fixed_size * fixed_count
                continue
            if isinstance(item, SwitchCaseItem):
                return None
            return None
        return total

    @cached_property
    def context_params(self) -> tuple[str, ...]:
        names: list[str] = []

        def add(name: str) -> None:
            if name not in names:
                names.append(name)

        for item in self.items:
            if isinstance(item, ListItem):
                for name in expr_paramrefs(item.len_expr):
                    add(name)
            elif isinstance(item, FieldItem) and isinstance(item.type_ref, StructType) and item.type_ref.decl is not None:
                for name in item.type_ref.decl.context_params:
                    add(name)
            elif isinstance(item, SwitchCaseItem):
                for name in item.context_params:
                    add(name)
        return tuple(names)


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
    items: tuple[EnumItemDecl, ...] = ()


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
    imports: tuple[str, ...]
    extension_xname: str | None
    typedefs: dict[str, TypedefDecl]
    xidtypes: dict[str, XidDecl]
    xidunions: dict[str, XidUnionDecl]
    unions: dict[str, UnionDecl]
    core_error_codes: EnumDecl | None
    enums: dict[str, EnumDecl]
    structs: dict[str, StructDecl]
    requests: dict[str, RequestDecl]
    events: dict[str, EventDecl]


class Resolver:
    def __init__(self, bindings: xcbxml.Bindings, imported_modules: dict[str, ModuleIR]) -> None:
        self.bindings = bindings
        self.imported_modules = imported_modules
        self.struct_types: dict[str, StructType] = {}
        self.union_types: dict[str, UnionType] = {}
        self.typedefs = {it.name: TypedefDecl(it.name, it.alias) for it in bindings.typedef}
        enum_decls = {
            it.name: EnumDecl(
                it.name,
                tuple(EnumItemDecl(field.name, field.value) for field in it.fields),
                is_mask=False,
            )
            for it in bindings.enum
        }
        self.mask_enum_names = self.collect_mask_enum_names()
        self.enums = {
            name: EnumDecl(decl.name, decl.items, is_mask=name in self.mask_enum_names)
            for name, decl in enum_decls.items()
        }
        self.xidtypes = {}
        for it in bindings.xidtype:
            merged_enum = enum_decls.get(zig_xid_name(it.name))
            self.xidtypes[it.name] = XidDecl(it.name, items=() if merged_enum is None else merged_enum.items)
        self.xidunions = {
            it.name: XidUnionDecl(it.name, tuple(it.fields))
            for it in bindings.xidunion
        }
        xid_enum_names = {zig_xid_name(xid_name) for xid_name in self.xidtypes}
        for name in tuple(self.enums):
            if name in xid_enum_names:
                del self.enums[name]
        if bindings.error or bindings.errorcopy:
            prefix = zig_extension_error_prefix(bindings.header) if bindings.extension_xname is not None else ""
            self.core_error_codes = EnumDecl(
                "Error",
                tuple(
                    [EnumItemDecl(f"{prefix}{it.name}", int(it.number)) for it in bindings.error]
                    + [EnumItemDecl(f"{prefix}{it.name}", int(it.number)) for it in bindings.errorcopy]
                ),
                is_mask=False,
            )
        else:
            self.core_error_codes = None

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
        for eventstruct in self.bindings.eventstruct:
            unions[eventstruct.name] = UnionDecl(name=eventstruct.name, items=(), raw_size=32)
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
            imports=tuple(self.bindings.imports),
            extension_xname=self.bindings.extension_xname,
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
        qualified = split_qualified_name(x_name)
        if qualified is not None:
            module_name, local_name = qualified
            module = self.imported_modules.get(module_name)
            if module is None:
                raise ValueError(f"unknown imported module: {module_name}")
            typedef = module.typedefs.get(local_name)
            resolved = typedef.alias if typedef is not None else local_name
            if resolved not in SCALAR_TYPES:
                raise ValueError(f"not a scalar type: {x_name}")
            return SCALAR_TYPES[resolved]
        resolved = self.resolve_typename(x_name)
        if resolved not in SCALAR_TYPES:
            raise ValueError(f"not a scalar type: {x_name}")
        return SCALAR_TYPES[resolved]

    def resolve_imported_type(self, resolved: str) -> TypeRef | None:
        for module_name, module in self.imported_modules.items():
            if resolved in module.xidtypes:
                return XidType(resolved, module_name=module_name)
            if resolved in module.xidunions:
                return XidUnionType(
                    resolved,
                    module.xidunions[resolved].members,
                    module_name=module_name,
                )
            if resolved in module.unions:
                union_type = self.union_types.setdefault(resolved, UnionType(resolved, module_name=module_name))
                union_type.decl = module.unions[resolved]
                return union_type
            if resolved in module.structs:
                struct_type = self.struct_types.setdefault(resolved, StructType(resolved, module_name=module_name))
                struct_type.decl = module.structs[resolved]
                return struct_type
        return None

    def resolve_imported_enum_module(self, enum_name: str) -> str | None:
        for module_name, module in self.imported_modules.items():
            if enum_name in module.enums:
                return module_name
        return None

    def resolve_imported_typedef_type(self, x_name: str) -> TypeRef | None:
        for module_name, module in self.imported_modules.items():
            typedef = module.typedefs.get(x_name)
            if typedef is None:
                continue
            alias = typedef.alias
            if alias in SCALAR_TYPES:
                return SCALAR_TYPES[alias]
            if alias in module.xidtypes:
                return XidType(alias, module_name=module_name)
            if alias in module.xidunions:
                return XidUnionType(alias, module.xidunions[alias].members, module_name=module_name)
            if alias in module.unions:
                union_type = self.union_types.setdefault(alias, UnionType(alias, module_name=module_name))
                union_type.decl = module.unions[alias]
                return union_type
            if alias in module.structs:
                struct_type = self.struct_types.setdefault(alias, StructType(alias, module_name=module_name))
                struct_type.decl = module.structs[alias]
                return struct_type
        return None

    def resolve_enum_type(self, enum_name: str, wire_name: str) -> EnumType:
        wire_type = self.resolve_wire_scalar(wire_name)
        qualified = split_qualified_name(enum_name)
        if qualified is not None:
            module_name, local_name = qualified
            if module_name == self.bindings.header:
                if local_name in self.enums:
                    return EnumType(local_name, wire_type)
                raise ValueError(f"unknown qualified enum type: {enum_name}")
            module = self.imported_modules.get(module_name)
            if module is None:
                raise ValueError(f"unknown imported module: {module_name}")
            if local_name in module.enums:
                return EnumType(local_name, wire_type, module_name=module_name)
            raise ValueError(f"unknown qualified enum type: {enum_name}")
        if enum_name in self.enums:
            return EnumType(enum_name, wire_type)
        imported_module_name = self.resolve_imported_enum_module(enum_name)
        if imported_module_name is not None:
            return EnumType(enum_name, wire_type, module_name=imported_module_name)
        raise ValueError(f"unknown enum type: {enum_name}")

    def resolve_type(self, x_name: str, *, enum_name: str | None = None, mask_name: str | None = None) -> TypeRef:
        if enum_name is not None:
            return self.resolve_enum_type(enum_name, x_name)
        if mask_name is not None:
            return MaskType(mask_name, self.resolve_wire_scalar(x_name))

        qualified = split_qualified_name(x_name)
        if qualified is not None:
            module_name, local_name = qualified
            module = self.imported_modules.get(module_name)
            if module is None:
                raise ValueError(f"unknown imported module: {module_name}")
            typedef = module.typedefs.get(local_name)
            resolved = typedef.alias if typedef is not None else local_name
            if resolved in SCALAR_TYPES:
                return SCALAR_TYPES[resolved]
            if resolved in module.xidtypes:
                return XidType(resolved, module_name=module_name)
            if resolved in module.xidunions:
                return XidUnionType(resolved, module.xidunions[resolved].members, module_name=module_name)
            if resolved in module.unions:
                union_type = self.union_types.setdefault(resolved, UnionType(resolved, module_name=module_name))
                union_type.decl = module.unions[resolved]
                return union_type
            if resolved in module.structs:
                struct_type = self.struct_types.setdefault(resolved, StructType(resolved, module_name=module_name))
                struct_type.decl = module.structs[resolved]
                return struct_type
            raise ValueError(f"unknown qualified type: {x_name}")

        resolved = self.resolve_typename(x_name)
        if resolved in SCALAR_TYPES:
            return SCALAR_TYPES[resolved]
        imported_typedef_type = self.resolve_imported_typedef_type(resolved)
        if imported_typedef_type is not None:
            return imported_typedef_type
        if resolved in self.xidtypes:
            return XidType(resolved)
        if resolved in self.xidunions:
            return XidUnionType(resolved, self.xidunions[resolved].members)
        if resolved in {it.name for it in self.bindings.union} | {it.name for it in self.bindings.eventstruct}:
            return self.union_types.setdefault(resolved, UnionType(resolved))
        imported = self.resolve_imported_type(resolved)
        if imported is not None:
            return imported
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

    def resolve_switch_case(self, item: xcbxml.CaseItem) -> SwitchCaseDecl:
        enum_name, enum_item = item.enum_ref
        return SwitchCaseDecl(
            enum_name=enum_name,
            enum_item=enum_item,
            items=self.resolve_items(item.fields),
            name=item.name,
        )

    def resolve_item(self, item: object) -> Item:
        if isinstance(item, xcbxml.Field):
            return self.resolve_field(item)
        if isinstance(item, xcbxml.Pad):
            if item.count is not None:
                return PadBytesItem(item.count)
            assert item.align is not None
            return PadAlignItem(int(item.align))
        if isinstance(item, xcbxml.RequiredStartAlign):
            return RequiredStartAlignItem(item.align, item.offset)
        if isinstance(item, xcbxml.ListField):
            return ListItem(
                name=item.name,
                item_type=self.resolve_type(item.item_type, enum_name=item.enum),
                len_expr=item.len_expr,
            )
        if isinstance(item, xcbxml.SwitchField):
            return MaskListItem(
                name=item.name,
                mask_field_name=item.fieldref.ref,
                cases=tuple(self.resolve_mask_case(case) for case in item.items),
            )
        if isinstance(item, xcbxml.CaseSwitchField):
            return SwitchCaseItem(
                name=item.name,
                fieldref_name=item.fieldref.ref,
                cases=tuple(self.resolve_switch_case(case) for case in item.items),
                align=tuple((it.align, it.offset) for it in item.required_start_align),
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
                    type_ref = fields[item.mask_field_name].type_ref
                    if not isinstance(type_ref, MaskType):
                        raise TypeError(f"mask field must use MaskType: {item.mask_field_name}")
                    item.mask_type = type_ref.render_zig()

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


def zig_xid_variant_name(name: str) -> str:
    zig_name = zig_xid_name(name)
    return zig_name[:1].lower() + zig_name[1:]


def zig_enum_item_name(name: str) -> str:
    if name and name[0].isdigit():
        return f'@"{name}"'
    if not name:
        return name
    parts = name.replace("-", "_").split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def zig_extension_name(name: str) -> str:
    if name == "XInputExtension":
        return "XINPUT"
    return "".join(ch if ch.isalnum() else "_" for ch in name)


def zig_extension_prefix(header: str) -> str:
    prefix = zig_enum_item_name(header)
    if len(prefix) >= 2 and prefix[0] == "X":
        prefix = "X" + prefix[1].upper() + prefix[2:]
    return prefix


def zig_extension_error_prefix(header: str) -> str:
    return zig_extension_prefix(header)


def split_qualified_name(name: str) -> tuple[str, str] | None:
    if ":" not in name:
        return None
    module_name, local_name = name.split(":", 1)
    return module_name, local_name


def unique_enum_items(items: tuple[EnumItemDecl, ...]) -> tuple[EnumItemDecl, ...]:
    seen: set[int] = set()
    result: list[EnumItemDecl] = []
    for item in items:
        if item.value in seen:
            continue
        seen.add(item.value)
        result.append(item)
    return tuple(result)


def duplicate_enum_items(items: tuple[EnumItemDecl, ...]) -> tuple[tuple[EnumItemDecl, EnumItemDecl], ...]:
    canonical_by_value: dict[int, EnumItemDecl] = {}
    result: list[tuple[EnumItemDecl, EnumItemDecl]] = []
    for item in items:
        canonical = canonical_by_value.get(item.value)
        if canonical is None:
            canonical_by_value[item.value] = item
            continue
        result.append((item, canonical))
    return tuple(result)


def emit_prelude(emit: Emit, module: ModuleIR) -> None:
    emit("// zig fmt: off")
    emit("// This file is generated by tools/genproto.py")
    emit()
    emit('const std = @import("std");')
    emit('const zio = @import("../io.zig");')
    emit('const wire = @import("../_wire.zig");')
    emit('const errors = @import("../_errors.zig");')
    emit('const extensions = @import("../_ext.zig");')
    if module.events:
        emit('const global_events = @import("events.zig");')
    for imported in module.imports:
        emit(f'const {imported} = @import("{imported}.zig");')
    emit("const DecodeError = errors.DecodeError;")
    emit("const AllocDecodeError = errors.AllocDecodeError;")
    emit("const BufferDecodeError = errors.BufferDecodeError;")
    emit()


def emit_xid_decl(emit: Emit, decl: XidDecl | XidUnionDecl) -> None:
    if isinstance(decl, XidDecl):
        xid_name = zig_xid_name(decl.name)
        emit(f"pub const {zig_xid_name(decl.name)} = enum(u32) {{")
        with emit.block():
            for item in unique_enum_items(decl.items):
                emit(f"{zig_enum_item_name(item.name)} = {item.value},")
            emit("_ ,".replace(" ", ""))
        emit("};")
        duplicates = duplicate_enum_items(decl.items)
        if duplicates:
            emit()
            emit(f"pub const {xid_name}_ = struct {{")
            with emit.block():
                for item, canonical in duplicates:
                    emit(
                        f"pub const {zig_enum_item_name(item.name)} = "
                        f"{xid_name}.{zig_enum_item_name(canonical.name)};"
                    )
            emit("};")
        emit()
        return

    emit(f"pub const {zig_xid_name(decl.name)} = union(enum) {{")
    with emit.block():
        for member in decl.members:
            emit(f"{zig_xid_variant_name(member)}: {zig_xid_name(member)},")
        emit("raw: u32,")
        emit("pub fn toInt(self: @This()) u32 {")
        with emit.block():
            emit("return switch (self) {")
            with emit.block():
                for member in decl.members:
                    variant = zig_xid_variant_name(member)
                    emit(f".{variant} => |value| @intFromEnum(value),")
                emit(".raw => |value| value,")
            emit("};")
        emit("}")
        emit()
        emit("pub fn encode(self: @This(), writer: anytype) void {")
        with emit.block():
            emit("writer.writeInt(u32, self.toInt());")
        emit("}")
        emit()
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            emit("return .{ .raw = try reader.takeInt(u32, .native) };")
        emit("}")
    emit("};")
    emit()


def emit_union_decl(emit: Emit, decl: UnionDecl) -> None:
    emit(f"pub const {decl.name} = struct {{")
    with emit.block():
        emit(f"raw: [{decl.raw_size}]u8,")
        emit()
        emit(f"pub fn fromRaw(raw: [{decl.raw_size}]u8) @This() {{")
        with emit.block():
            emit("return .{ .raw = raw };")
        emit("}")
        emit()
        emit(f"pub fn asRaw(self: @This()) [{decl.raw_size}]u8 {{")
        with emit.block():
            emit("return self.raw;")
        emit("}")
        emit()
        emit("pub fn fromEvent(event: anytype) @This() {")
        with emit.block():
            emit("return .{ .raw = event.toBytes() };")
        emit("}")
        emit()
        emit("pub fn encode(self: @This(), writer: anytype) void {")
        with emit.block():
            emit("writer.write(self.raw[0..]);")
        emit("}")
        emit()
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            emit(f"var raw: [{decl.raw_size}]u8 = undefined;")
            emit(f"@memcpy(raw[0..], try reader.take({decl.raw_size}));")
            emit("return .{ .raw = raw };")
        emit("}")
        for item in decl.items:
            if isinstance(item, PadBytesItem):
                continue
            emit()
            suffix = zig_enum_item_name(item.name)
            if isinstance(item, FieldItem):
                type_name = item.type_ref.render_zig()
            elif isinstance(item, ListItem):
                fixed_count = item.fixed_count()
                if fixed_count is None:
                    raise NotImplementedError(f"union list requires fixed count: {item.name}")
                type_name = f"[{fixed_count}]{item.item_type.render_zig()}"
            else:
                raise NotImplementedError(f"unsupported union item method emission: {item!r}")
            emit(f"pub fn from{suffix}(value: {type_name}) @This() {{")
            with emit.block():
                emit(f"var raw = std.mem.zeroes([{decl.raw_size}]u8);")
                emit("var writer_impl = zio.FixedBufferWriter.init(&raw);")
                emit("const writer = &writer_impl;")
                if isinstance(item, FieldItem):
                    item.type_ref.emit_encode(emit, "value")
                else:
                    fixed_size = item.item_type.fixed_wire_size()
                    assert fixed_size is not None
                    if fixed_size == 1:
                        emit("writer.write(value[0..]);")
                    else:
                        emit("for (value) |elem| {")
                        with emit.block():
                            item.item_type.emit_encode(emit, "elem")
                        emit("}")
                emit("return .{ .raw = raw };")
            emit("}")
            emit()
            emit(f"pub fn as{suffix}(self: @This()) DecodeError!{type_name} {{")
            with emit.block():
                emit("var reader_impl: std.Io.Reader = .fixed(&self.raw);")
                emit("const reader = &reader_impl;")
                if isinstance(item, FieldItem):
                    item.type_ref.emit_decode(emit, "value")
                else:
                    fixed_count = item.fixed_count()
                    assert fixed_count is not None
                    elem_type = item.item_type.render_zig()
                    fixed_size = item.item_type.fixed_wire_size()
                    assert fixed_size is not None
                    emit(f"var value: [{fixed_count}]{elem_type} = undefined;")
                    if fixed_size == 1:
                        emit(f"@memcpy(value[0..], try reader.take({fixed_count}));")
                    else:
                        emit("for (&value) |*elem| {")
                        with emit.block():
                            item.item_type.emit_decode(emit, "elem_value")
                            emit("elem.* = elem_value;")
                        emit("}")
                emit("return value;")
            emit("}")
    emit("};")
    emit()


def render_field_name(name: str) -> str:
    return name


def render_local_name(name: str) -> str:
    if name == "type":
        return '@"type"'
    return name


def render_expr(expr: Expr, *, owner_expr: str | None = None, list_elem_name: str | None = None) -> str:
    if isinstance(expr, int):
        return str(expr)
    if isinstance(expr, xcbxml.FieldRef):
        if list_elem_name is not None:
            return f"{list_elem_name}.{render_field_name(expr.ref)}"
        if owner_expr is not None:
            return f"{owner_expr}.{render_field_name(expr.ref)}"
        return render_local_name(expr.ref)
    if isinstance(expr, xcbxml.ParamRef):
        if owner_expr is not None:
            return f"{owner_expr}.{render_field_name(expr.ref)}"
        return render_local_name(expr.ref)
    if isinstance(expr, xcbxml.ListElementRef):
        if list_elem_name is None:
            raise ValueError("listelement-ref requires list element context")
        return list_elem_name
    if isinstance(expr, xcbxml.PopCount):
        return f"@popCount({render_expr(expr.expr, owner_expr=owner_expr, list_elem_name=list_elem_name)})"
    if isinstance(expr, xcbxml.SumOf):
        list_name = render_local_name(expr.ref) if owner_expr is None else f"{owner_expr}.{render_field_name(expr.ref)}"
        inner = render_expr(expr.expr, owner_expr=owner_expr, list_elem_name="elem")
        return (
            f"(blk: {{ var total: usize = 0; "
            f"for ({list_name}) |elem| total += @as(usize, {inner}); "
            f"break :blk total; }})"
        )
    if isinstance(expr, xcbxml.Op):
        op = {
            "+": "+",
            "-": "-",
            "*": "*",
            "/": "/",
        }.get(expr.op)
        if op is None:
            raise NotImplementedError(f"unsupported expression operator: {expr.op}")
        return (
            f"({render_expr(expr.left, owner_expr=owner_expr, list_elem_name=list_elem_name)} "
            f"{op} "
            f"{render_expr(expr.right, owner_expr=owner_expr, list_elem_name=list_elem_name)})"
        )
    raise TypeError(f"unsupported expression: {expr!r}")


def expr_uses_fieldref(expr: Expr | None, name: str) -> bool:
    if expr is None:
        return False
    if isinstance(expr, int):
        return False
    if isinstance(expr, xcbxml.FieldRef):
        return expr.ref == name
    if isinstance(expr, xcbxml.ParamRef):
        return expr.ref == name
    if isinstance(expr, xcbxml.ListElementRef):
        return False
    if isinstance(expr, xcbxml.PopCount):
        return expr_uses_fieldref(expr.expr, name)
    if isinstance(expr, xcbxml.SumOf):
        return expr.ref == name or expr_uses_fieldref(expr.expr, name)
    if isinstance(expr, xcbxml.Op):
        return expr_uses_fieldref(expr.left, name) or expr_uses_fieldref(expr.right, name)
    raise TypeError(f"unsupported expression: {expr!r}")


def expr_paramrefs(expr: Expr | None) -> tuple[str, ...]:
    if expr is None or isinstance(expr, int):
        return ()
    if isinstance(expr, xcbxml.FieldRef):
        return ()
    if isinstance(expr, xcbxml.ParamRef):
        return (expr.ref,)
    if isinstance(expr, xcbxml.ListElementRef):
        return ()
    if isinstance(expr, xcbxml.PopCount):
        return expr_paramrefs(expr.expr)
    if isinstance(expr, xcbxml.SumOf):
        return expr_paramrefs(expr.expr)
    if isinstance(expr, xcbxml.Op):
        return expr_paramrefs(expr.left) + expr_paramrefs(expr.right)
    raise TypeError(f"unsupported expression: {expr!r}")


def expr_fieldrefs(expr: Expr | None) -> tuple[str, ...]:
    if expr is None or isinstance(expr, int):
        return ()
    if isinstance(expr, xcbxml.FieldRef):
        return (expr.ref,)
    if isinstance(expr, xcbxml.ParamRef):
        return ()
    if isinstance(expr, xcbxml.ListElementRef):
        return ()
    if isinstance(expr, xcbxml.PopCount):
        return expr_fieldrefs(expr.expr)
    if isinstance(expr, xcbxml.SumOf):
        refs = (expr.ref,)
        return refs + expr_fieldrefs(expr.expr)
    if isinstance(expr, xcbxml.Op):
        return expr_fieldrefs(expr.left) + expr_fieldrefs(expr.right)
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


def body_items(items: tuple[Item, ...], *, uses_header_slot: bool) -> tuple[Item, ...]:
    return items[1:] if uses_header_slot and header_item(items) is not None else items


def header_byte1_expr(field: FieldItem) -> str:
    value_expr = f"self.{render_field_name(field.name)}"
    type_ref = field.type_ref
    if isinstance(type_ref, ScalarType):
        if type_ref.wire_size != 1:
            raise NotImplementedError(f"unsupported header byte field: {field.name}")
        if type_ref.zig_name == "bool":
            return f"@intFromBool({value_expr})"
        if type_ref.zig_name == "u8":
            return value_expr
        return f"@as(u8, @bitCast({value_expr}))"
    if isinstance(type_ref, EnumType) and type_ref.wire_type.wire_size == 1:
        return f"@intCast(@intFromEnum({value_expr}))"
    if isinstance(type_ref, MaskType) and type_ref.wire_type.wire_size == 1:
        if type_ref.wire_type.zig_name == "u8":
            return value_expr
        return f"@as(u8, @bitCast({value_expr}))"
    raise NotImplementedError(f"unsupported header byte field: {field.name}")


def reply_decode_mode(decl: StructDecl) -> str:
    for item in decl.items:
        if isinstance(item, ListItem):
            if item.is_inline_fixed():
                continue
            if item.item_type.fixed_wire_size() != 1:
                return "alloc"
        elif isinstance(item, SwitchCaseItem):
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


def emit_payload_decl_fields(
    emit: Emit,
    items: tuple[Item, ...],
    *,
    const_struct_lists: bool = False,
) -> None:
    for item in items:
        if isinstance(item, FieldItem) and item.derived_from is not None:
            continue
        if isinstance(item, ListItem):
            item.emit_decl(emit, const_struct_list=const_struct_lists)
        else:
            item.emit_decl(emit)


def payload_byte_len_expr(items: tuple[Item, ...], owner_expr: str) -> str:
    terms: list[str] = []
    previous_item: Item | None = None
    for item in items:
        terms.append(item.byte_len_term(owner_expr, previous_item))
        previous_item = item
    return " + ".join(terms) if terms else "0"


def decoded_item_byte_len_term(item: Item, previous_item: Item | None = None) -> str:
    if isinstance(item, FieldItem):
        return item.type_ref.byte_len_expr(render_local_name(item.name))
    if isinstance(item, PadBytesItem):
        return str(item.count)
    if isinstance(item, PadAlignItem):
        if not isinstance(previous_item, ListItem):
            raise NotImplementedError("pad-align decoded byteLen requires preceding list item")
        if item.align != 4:
            raise NotImplementedError(f"pad-align decoded byteLen only supports align=4, got {item.align}")
        return f"wire.pad4({previous_item.decoded_payload_len_expr()})"
    if isinstance(item, RequiredStartAlignItem):
        raise NotImplementedError("required-start-align decoded length should use reader.seek tracking")
    if isinstance(item, ListItem):
        return item.decoded_payload_len_expr()
    if isinstance(item, SwitchCaseItem):
        return f"{render_local_name(item.name)}.byteLen()"
    if isinstance(item, MaskListItem):
        raise NotImplementedError(f"mask-list decoded byteLen is not implemented for {item.name}")
    raise TypeError(f"unsupported item: {item!r}")


def decoded_payload_byte_len_expr(items: tuple[Item, ...]) -> str:
    terms: list[str] = []
    previous_item: Item | None = None
    for item in items:
        terms.append(decoded_item_byte_len_term(item, previous_item))
        previous_item = item
    return " + ".join(terms) if terms else "0"


def payload_has_required_start_align(items: tuple[Item, ...]) -> bool:
    return any(isinstance(item, RequiredStartAlignItem) for item in items)


def payload_needs_offset_tracking(items: tuple[Item, ...]) -> bool:
    return False


def list_pad_seek_name(item: ListItem) -> str:
    return f"{render_local_name(item.name)}_start_seek"


def emit_payload_byte_len(emit: Emit, items: tuple[Item, ...], owner_expr: str) -> None:
    expr = payload_byte_len_expr(items, owner_expr)
    if owner_expr not in expr:
        emit(f"_ = {owner_expr};")
    emit(f"return {expr};")


def emit_payload_encode_body(
    emit: Emit,
    items: tuple[Item, ...],
    owner_expr: str,
    previous_item: Item | None = None,
) -> None:
    current_previous = previous_item
    for index, item in enumerate(items):
        next_item = items[index + 1] if index + 1 < len(items) else None
        if isinstance(item, RequiredStartAlignItem):
            emit(f"const required_pad = wire.requiredPad(writer.seek, {item.align}, {item.offset});")
            emit("writer.splatByte(0, required_pad);")
        elif isinstance(item, SwitchCaseItem):
            field_name = render_field_name(item.name)
            emit(f"{owner_expr}.{field_name}.encode(writer);")
        elif (
            isinstance(item, ListItem)
            and isinstance(next_item, PadAlignItem)
            and next_item.align == 4
            and item.item_type.fixed_wire_size() is None
        ):
            emit(f"const {list_pad_seek_name(item)} = writer.seek;")
            item.emit_encode(emit, owner_expr, current_previous)
        else:
            item.emit_encode(emit, owner_expr, current_previous)
        current_previous = item


def emit_struct_encode(emit: Emit, decl: StructDecl) -> None:
    emit("pub fn encode(self: @This(), writer: anytype) void {")
    with emit.block():
        emit_payload_encode_body(emit, decl.items, "self")
    emit("}")
    emit()


def emit_struct_decode_signature(emit: Emit, decl: StructDecl) -> None:
    ctx = "".join(f"{render_field_name(name)}: anytype, " for name in decl.context_params)
    if decl.is_dynamic:
        emit(f"pub fn decode(allocator: std.mem.Allocator, {ctx}reader: *std.Io.Reader) AllocDecodeError!@This() {{")
    else:
        emit(f"pub fn decode({ctx}reader: *std.Io.Reader) DecodeError!@This() {{")


def emit_payload_decode_body(
    emit: Emit,
    items: tuple[Item, ...],
    previous_item: Item | None = None,
    decode_mode: str = "alloc",
) -> None:
    current_previous = previous_item
    for index, item in enumerate(items):
        next_item = items[index + 1] if index + 1 < len(items) else None
        if isinstance(item, RequiredStartAlignItem):
            emit(f"const required_pad = wire.requiredPad(reader.seek, {item.align}, {item.offset});")
            emit("if (required_pad != 0) _ = try reader.take(required_pad);")
        elif isinstance(item, SwitchCaseItem):
            params = "".join(f"{render_local_name(name)}, " for name in item.context_params)
            emit(
                f"const {render_local_name(item.name)} = "
                f"try {item.require_type_name()}.decode("
                f"allocator, {render_local_name(item.fieldref_name)}, {params}reader);"
            )
        elif (
            isinstance(item, ListItem)
            and isinstance(next_item, PadAlignItem)
            and next_item.align == 4
            and item.item_type.fixed_wire_size() is None
        ):
            emit(f"const {list_pad_seek_name(item)} = reader.seek;")
            item.emit_decode(emit, current_previous, decode_mode)
        elif isinstance(item, ListItem):
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
            if isinstance(item, FieldItem | ListItem | SwitchCaseItem):
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
            elif isinstance(item, FieldItem) and isinstance(item.type_ref, StructType) and item.type_ref.is_dynamic:
                emit(f"self.{render_field_name(item.name)}.deinit(allocator);")
            elif isinstance(item, SwitchCaseItem):
                emit(f"self.{render_field_name(item.name)}.deinit(allocator);")
    emit("}")
    emit()


def emit_struct_decl(emit: Emit, decl: StructDecl) -> None:
    emit(f"pub const {decl.name} = struct {{")
    with emit.block():
        emit_switch_case_decls(emit, decl.name, decl.items)
        emit_payload_decl_fields(emit, decl.items)
        emit()
        emit_struct_encode(emit, decl)
        emit_struct_decode(emit, decl)
        emit_struct_deinit(emit, decl)
    emit("};")
    emit()


def emit_reply_decl(emit: Emit, request: RequestDecl) -> None:
    assert request.reply is not None
    items = request.reply.items
    header = header_item(items)
    body = body_items(items, uses_header_slot=True)
    decl = StructDecl(name=reply_name(request.name), items=items)
    decode_mode = "fixed" if not decl.is_dynamic else reply_decode_mode(decl)
    uses_reply_length = any(item_uses_fieldref(item, "length") for item in body)

    emit(f"pub const {reply_name(request.name)} = struct {{")
    with emit.block():
        emit_switch_case_decls(emit, reply_name(request.name), items)
        emit_payload_decl_fields(emit, items)
        emit()
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
            emit("_ = try reader.takeInt(u16, .native);")
            if uses_reply_length:
                emit("const length = try reader.takeInt(u32, .native);")
            else:
                emit("_ = try reader.takeInt(u32, .native);")
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
        emit(f"pub const mask_type = {item.require_mask_type()};")
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


def emit_switch_case_decl(emit: Emit, item: SwitchCaseItem) -> None:
    emit(f"pub const {item.require_type_name()} = union(enum) {{")
    with emit.block():
        for case in item.cases:
            variant_name = case.name or zig_enum_item_name(case.enum_item)
            emit(f"{render_field_name(variant_name)}: struct {{")
            with emit.block():
                emit_payload_decl_fields(emit, case.items)
            emit("},")
        emit()
        emit("pub fn encode(self: @This(), writer: anytype) void {")
        with emit.block():
            emit("switch (self) {")
            with emit.block():
                for case in item.cases:
                    variant_name = case.name or zig_enum_item_name(case.enum_item)
                    emit(f".{render_field_name(variant_name)} => |value| {{")
                    with emit.block():
                        emit_payload_encode_body(emit, case.items, "value")
                    emit("},")
            emit("}")
        emit("}")
        emit()
        ctx = "".join(f"{render_field_name(name)}: anytype, " for name in item.context_params)
        emit(
            f"pub fn decode("
            f"allocator: std.mem.Allocator, discriminator: anytype, {ctx}reader: *std.Io.Reader"
            f") AllocDecodeError!@This() {{"
        )
        with emit.block():
            emit("return switch (discriminator) {")
            with emit.block():
                for case in item.cases:
                    variant_name = case.name or zig_enum_item_name(case.enum_item)
                    emit(f"{case.enum_name}.{zig_enum_item_name(case.enum_item)} => blk: {{")
                    with emit.block():
                        emit_payload_decode_body(emit, case.items, decode_mode="alloc")
                        emit("break :blk .{")
                        with emit.block():
                            emit(f".{render_field_name(variant_name)} = .{{")
                            with emit.block():
                                for case_item in case.items:
                                    if isinstance(case_item, FieldItem) and case_item.derived_from is not None:
                                        continue
                                    if isinstance(case_item, FieldItem | ListItem | SwitchCaseItem):
                                        emit(
                                            f".{render_field_name(case_item.name)} = "
                                            f"{render_local_name(case_item.name)},"
                                        )
                            emit("},")
                        emit("};")
                    emit("},")
            emit("else => std.debug.panic(\"unsupported switch discriminator\", .{}),")
            emit("};")
        emit("}")
        emit()
        emit("pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {")
        with emit.block():
            has_dynamic_case = False
            for case in item.cases:
                if any(isinstance(case_item, ListItem) and not case_item.is_inline_fixed() for case_item in case.items):
                    has_dynamic_case = True
                    break
            if not has_dynamic_case:
                emit("_ = self;")
                emit("_ = allocator;")
                emit("return;")
                emit()
            emit("switch (self.*) {")
            with emit.block():
                for case in item.cases:
                    variant_name = case.name or zig_enum_item_name(case.enum_item)
                    dynamic_case = any(
                        isinstance(case_item, ListItem) and not case_item.is_inline_fixed()
                        for case_item in case.items
                    )
                    if dynamic_case:
                        emit(f".{render_field_name(variant_name)} => |*value| {{")
                    else:
                        emit(f".{render_field_name(variant_name)} => {{")
                    with emit.block():
                        for case_item in case.items:
                            if isinstance(case_item, ListItem) and not case_item.is_inline_fixed():
                                field_name = render_field_name(case_item.name)
                                if isinstance(case_item.item_type, StructType) and case_item.item_type.is_dynamic:
                                    emit(f"for (value.{field_name}) |*elem| elem.deinit(allocator);")
                                emit(f"allocator.free(value.{field_name});")
                    emit("},")
            emit("}")
        emit("}")
    emit("};")
    emit()


def emit_switch_case_decls(emit: Emit, prefix: str, items: tuple[Item, ...]) -> None:
    for item in items:
        if isinstance(item, SwitchCaseItem):
            item.set_generated_name(prefix)
            emit_switch_case_decl(emit, item)


def emit_request_aux_decls(emit: Emit, request: RequestDecl) -> None:
    for item in request.items:
        if isinstance(item, MaskListItem):
            emit_mask_list_decl(emit, item)
    emit_switch_case_decls(emit, request.name, request.items)


def request_uses_header_slot(module: ModuleIR, request: RequestDecl) -> bool:
    return module.extension_xname is None and header_item(request.items) is not None


def emit_request_header_byte1(emit: Emit, module: ModuleIR, request: RequestDecl) -> None:
    emit("pub fn headerByte1(self: @This()) u8 {")
    with emit.block():
        first = header_item(request.items) if request_uses_header_slot(module, request) else None
        if isinstance(first, FieldItem):
            emit(f"return {header_byte1_expr(first)};")
        else:
            emit("_ = self;")
            emit("return 0;")
    emit("}")
    emit()


def emit_request_encode(emit: Emit, module: ModuleIR, request: RequestDecl) -> None:
    emit("pub fn encode(self: @This(), writer: anytype) void {")
    with emit.block():
        items = body_items(request.items, uses_header_slot=request_uses_header_slot(module, request))
        first = header_item(request.items) if request_uses_header_slot(module, request) else None
        if not any(isinstance(item, (FieldItem, ListItem, MaskListItem)) for item in items):
            emit("_ = self;")
        if not items:
            emit("_ = writer;")
        emit_payload_encode_body(
            emit,
            items,
            "self",
            first,
        )
    emit("}")
    emit()


def emit_request_decl(emit: Emit, module: ModuleIR, request: RequestDecl) -> None:
    emit_request_aux_decls(emit, request)
    emit(f"pub const {request_decl_name(request.name)} = struct {{")
    with emit.block():
        emit(f"pub const opcode: u8 = {request.opcode};")
        if module.extension_xname is None:
            emit("pub const extension: ?extensions.Extension = null;")
        else:
            emit(f"pub const extension: ?extensions.Extension = .{zig_extension_name(module.extension_xname)};")
        if request.reply is None:
            emit("pub const Reply = void;")
        else:
            emit(f"pub const Reply = {reply_name(request.name)};")
        emit()
        emit_payload_decl_fields(emit, request.items, const_struct_lists=True)
        emit()
        emit_request_header_byte1(emit, module, request)
        emit_request_encode(emit, module, request)
    emit("};")
    emit()


def event_struct_name(name: str) -> str:
    return f"{name}Event"


def event_tag_name(module: ModuleIR, name: str) -> str:
    if module.extension_xname is None:
        return name
    return f"{zig_extension_prefix(module.header)}{name}"


def split_dynamic_event_items(items: tuple[Item, ...]) -> tuple[tuple[Item, ...], tuple[Item, ...]] | None:
    first_dynamic: int | None = None
    for index, item in enumerate(items):
        if isinstance(item, ListItem) and not item.is_inline_fixed():
            first_dynamic = index
            break
    if first_dynamic is None:
        return None
    prefix = items[:first_dynamic]
    body = items[first_dynamic:]
    for item in body:
        if isinstance(item, PadBytesItem | PadAlignItem | RequiredStartAlignItem | ListItem):
            continue
        raise NotImplementedError("dynamic XGE events only support trailing list payloads")
    return prefix, body


def dynamic_event_body_fieldrefs(items: tuple[Item, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in items:
        if isinstance(item, ListItem):
            for name in expr_fieldrefs(item.len_expr):
                if name not in refs:
                    refs.append(name)
    return tuple(refs)


def emit_dynamic_body_decl(emit: Emit, event_name: str, body_items: tuple[Item, ...]) -> None:
    body_decl = StructDecl(name=f"{event_name}Body", items=body_items)
    emit(f"pub const Body = struct {{")
    with emit.block():
        emit_payload_decl_fields(emit, body_items)
        emit()
        emit_struct_deinit(emit, body_decl)
    emit("};")
    emit()


def emit_event_decl(emit: Emit, decl: EventDecl) -> None:
    xge_body_dynamic = reply_decode_mode(StructDecl(name=event_struct_name(decl.name), items=decl.items)) == "alloc"
    dynamic_parts = split_dynamic_event_items(decl.items) if decl.xge == "true" and xge_body_dynamic else None
    emit(f"pub const {event_struct_name(decl.name)} = struct {{")
    with emit.block():
        if decl.xge == "true":
            emit("extension: u8,")
            emit("length: u32,")
            emit("event_type: u16,")
            if dynamic_parts is not None:
                prefix_items, dynamic_body_items = dynamic_parts
                emit_payload_decl_fields(emit, prefix_items)
                emit("_body: []const u8,")
                emit()
                emit_dynamic_body_decl(emit, decl.name, dynamic_body_items)
            elif not xge_body_dynamic:
                emit_payload_decl_fields(emit, decl.items)
        else:
            emit_payload_decl_fields(emit, decl.items)
        emit()
        if dynamic_parts is not None:
            emit("pub fn getBody(self: @This(), allocator: std.mem.Allocator) AllocDecodeError!Body {")
            with emit.block():
                emit("var reader_impl: std.Io.Reader = .fixed(self._body);")
                emit("const reader = &reader_impl;")
                prefix_items, dynamic_body_items = dynamic_parts
                used_fieldrefs = set(dynamic_event_body_fieldrefs(dynamic_body_items))
                for item in prefix_items:
                    if isinstance(item, FieldItem) and item.name in used_fieldrefs:
                        local_name = render_local_name(item.name)
                        emit(f"const {local_name} = self.{render_field_name(item.name)};")
                    elif isinstance(item, FieldItem | PadBytesItem):
                        continue
                    elif isinstance(item, PadAlignItem):
                        raise NotImplementedError("dynamic XGE event prefix pad-align is not supported")
                    elif isinstance(item, RequiredStartAlignItem):
                        raise NotImplementedError("dynamic XGE event prefix required_start_align is not supported")
                    elif isinstance(item, ListItem | SwitchCaseItem | MaskListItem):
                        raise NotImplementedError("unexpected dynamic item in XGE event prefix")
                emit_payload_decode_body(emit, dynamic_body_items, decode_mode="alloc")
                emit("return .{")
                with emit.block():
                    for item in dynamic_body_items:
                        if isinstance(item, ListItem):
                            emit(f".{render_field_name(item.name)} = {render_local_name(item.name)},")
                emit("};")
            emit("}")
            emit()
        if decl.xge != "true":
            emit("pub fn toBytes(self: @This()) [32]u8 {")
            with emit.block():
                emit("var packet: [32]u8 = std.mem.zeroes([32]u8);")
                emit("var writer_impl = zio.FixedBufferWriter.init(&packet);")
                emit("const writer = &writer_impl;")
                if decl.no_sequence_number == "true":
                    emit(f"writer.writeByte({decl.number});")
                    for item in decl.items:
                        item.emit_encode(emit, "self")
                else:
                    header = header_item(decl.items)
                    body = body_items(decl.items, uses_header_slot=True)
                    emit(f"writer.writeByte({decl.number});")
                    if isinstance(header, FieldItem):
                        emit(f"writer.writeByte({header_byte1_expr(header)});")
                    else:
                        emit("writer.writeByte(0);")
                    emit("writer.writeInt(u16, 0);")
                    current_previous = header
                    for item in body:
                        item.emit_encode(emit, "self", current_previous)
                        current_previous = item
                emit("return packet;")
            emit("}")
            emit()
        emit("pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {")
        with emit.block():
            if dynamic_parts is not None:
                emit("const header = try reader.peek(12);")
                emit("const length = std.mem.readInt(u32, header[4..8], .native);")
                emit("const packet = try reader.peek(32 + @as(usize, length) * 4);")
                emit("_ = try reader.takeByte();")
                emit("const extension = try reader.takeByte();")
                emit("_ = try reader.takeInt(u16, .native);")
                emit("_ = try reader.takeInt(u32, .native);")
                emit("const event_type = try reader.takeInt(u16, .native);")
                prefix_items, _ = dynamic_parts
                for item in prefix_items:
                    if isinstance(item, FieldItem):
                        item.emit_decode(emit)
                    elif isinstance(item, PadBytesItem):
                        item.emit_decode(emit)
                    else:
                        raise NotImplementedError("dynamic XGE event prefix item is not supported")
                emit("const body = packet[reader.seek..];")
                emit("const remaining_packet_len = packet.len - reader.seek;")
                emit("if (remaining_packet_len != 0) _ = try reader.take(remaining_packet_len);")
                emit("return .{")
                with emit.block():
                    emit(".extension = extension,")
                    emit(".length = length,")
                    emit(".event_type = event_type,")
                    for item in prefix_items:
                        if isinstance(item, FieldItem):
                            emit(f".{render_field_name(item.name)} = {render_local_name(item.name)},")
                    emit("._body = body,")
                emit("};")
            elif decl.no_sequence_number == "true":
                emit_payload_decode_body(emit, decl.items)
                emit_payload_decode_return(emit, decl.items)
            else:
                emit("_ = try reader.takeByte();")
                if decl.xge == "true":
                    emit("const extension = try reader.takeByte();")
                    emit("_ = try reader.takeInt(u16, .native);")
                    emit("const length = try reader.takeInt(u32, .native);")
                    emit("const event_type = try reader.takeInt(u16, .native);")
                    if xge_body_dynamic:
                        emit("_ = try reader.take(22);")
                        emit("_ = try reader.take(@as(usize, length) * 4);")
                        emit("return .{")
                        with emit.block():
                            emit(".extension = extension,")
                            emit(".length = length,")
                            emit(".event_type = event_type,")
                        emit("};")
                    else:
                        emit("const payload_start_seek = reader.seek;")
                        emit_payload_decode_body(emit, decl.items)
                        emit("const xge_body_len = reader.seek - payload_start_seek;")
                        emit("const total_body_len = 22 + @as(usize, length) * 4;")
                        emit("if (xge_body_len < total_body_len) _ = try reader.take(total_body_len - xge_body_len);")
                        emit("return .{")
                        with emit.block():
                            emit(".extension = extension,")
                            emit(".length = length,")
                            emit(".event_type = event_type,")
                            for item in decl.items:
                                if isinstance(item, FieldItem) and item.derived_from is not None:
                                    continue
                                if isinstance(item, FieldItem | ListItem | SwitchCaseItem):
                                    emit(f".{render_field_name(item.name)} = {render_local_name(item.name)},")
                        emit("};")
                else:
                    header = header_item(decl.items)
                    body = body_items(decl.items, uses_header_slot=True)
                    if isinstance(header, FieldItem):
                        header.emit_decode(emit)
                    elif isinstance(header, PadBytesItem):
                        header.emit_decode(emit)
                    else:
                        emit("_ = try reader.take(1);")
                    emit("_ = try reader.takeInt(u16, .native);")
                    emit_payload_decode_body(emit, body, header)
                    emit_payload_decode_return(emit, decl.items)
        emit("}")
    emit("};")
    emit()


def emit_decode_event(emit: Emit, module: ModuleIR, events: dict[str, EventDecl]) -> None:
    standard_events = {
        name: decl
        for name, decl in events.items()
        if decl.xge != "true" or module.extension_xname is None
    }
    xge_events = {
        name: decl
        for name, decl in events.items()
        if decl.xge == "true" and module.extension_xname is not None
    }

    if standard_events:
        emit("pub fn decodeEvent(reader: *std.Io.Reader) DecodeError!global_events.Event {")
        with emit.block():
            emit("const code = (try reader.peek(1))[0] & 0x7f;")
            emit("return switch (code) {")
            with emit.block():
                for name in sorted(standard_events, key=lambda n: standard_events[n].number):
                    decl = standard_events[name]
                    emit(
                        f'{decl.number} => .{{ .{event_tag_name(module, name)} = try {event_struct_name(name)}.decode(reader) }},'
                    )
                emit("else => blk: {")
                with emit.block():
                    emit("const packet = try reader.take(32);")
                    emit("var raw: [32]u8 = undefined;")
                    emit("@memcpy(raw[0..], packet);")
                    emit("break :blk .{ .Unknown = .{")
                    with emit.block():
                        emit(".code = packet[0] & 0x7f,")
                        emit(".sequence = std.mem.readInt(u16, packet[2..4], .native),")
                        emit(".raw = raw,")
                    emit("} };")
                emit("},")
            emit("};")
        emit("}")
        emit()

    if not xge_events:
        return

    emit("pub fn decodeXgeEvent(reader: *std.Io.Reader) DecodeError!global_events.Event {")
    with emit.block():
        emit("const header = try reader.peek(10);")
        emit("const event_type = std.mem.readInt(u16, header[8..10], .native);")
        emit("return switch (event_type) {")
        with emit.block():
            for name in sorted(xge_events, key=lambda n: xge_events[n].number):
                decl = xge_events[name]
                emit(
                    f'{decl.number} => .{{ .{event_tag_name(module, name)} = try {event_struct_name(name)}.decode(reader) }},'
                )
            emit("else => .{ .GEUnknown = try xproto.GeGenericEvent.decode(reader) },")
        emit("};")
    emit("}")
    emit()


def render_module(module: ModuleIR) -> str:
    emit = Emit()
    emit_prelude(emit, module)

    for name in sorted(module.xidtypes):
        emit_xid_decl(emit, module.xidtypes[name])
    for name in sorted(module.xidunions):
        emit_xid_decl(emit, module.xidunions[name])
    for name in sorted(module.unions):
        emit_union_decl(emit, module.unions[name])
    if module.core_error_codes is not None:
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
        emit_request_decl(emit, module, request)
    for name in sorted(module.events, key=lambda n: module.events[n].number):
        emit_event_decl(emit, module.events[name])
    if module.events:
        emit_decode_event(emit, module, module.events)

    return emit.render()


def event_modules(modules: dict[str, ModuleIR]) -> tuple[ModuleIR, ...]:
    return tuple(module for module in modules.values() if module.events)


def emit_global_events_prelude(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("// zig fmt: off")
    emit("// This file is generated by tools/genproto.py")
    emit()
    emit('const std = @import("std");')
    emit('const errors = @import("../_errors.zig");')
    emit('const extensions = @import("../_ext.zig");')
    for module in modules:
        emit(f'const {module.header} = @import("{module.header}.zig");')
    emit("const DecodeError = errors.DecodeError;")
    emit()


def emit_global_unknown_event(emit: Emit) -> None:
    emit("pub const UnknownEvent = struct {")
    with emit.block():
        emit("code: u8,")
        emit("sequence: u16,")
        emit("raw: [32]u8,")
    emit("};")
    emit()


def emit_global_event_union(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("pub const Event = union(enum) {")
    with emit.block():
        emit("Unknown: UnknownEvent,")
        emit("GEUnknown: xproto.GeGenericEvent,")
        for module in modules:
            for name in sorted(module.events, key=lambda n: module.events[n].number):
                emit(f"{event_tag_name(module, name)}: {module.header}.{event_struct_name(name)},")
    emit("};")
    emit()


def extension_max_event_num(module: ModuleIR) -> int:
    numbers = [
        event.number
        for event in module.events.values()
        if event.xge != "true" or module.extension_xname is None
    ]
    if not numbers:
        return 0
    return max(numbers)


def extension_max_xge_event_num(module: ModuleIR) -> int:
    numbers = [
        event.number
        for event in module.events.values()
        if event.xge == "true" and module.extension_xname is not None
    ]
    if not numbers:
        return 0
    return max(numbers)


def emit_extension_event_specs(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("pub const ExtensionEventSpec = struct {")
    with emit.block():
        emit("max_event_num: u8,")
        emit("decode: ?*const fn (*std.Io.Reader) DecodeError!Event,")
        emit("max_xge_event_num: u16,")
        emit("decode_xge: ?*const fn (*std.Io.Reader) DecodeError!Event,")
    emit("};")
    emit()

    for module in modules:
        has_standard_events = any(
            event.xge != "true" or module.extension_xname is None for event in module.events.values()
        )
        has_xge_events = any(
            event.xge == "true" and module.extension_xname is not None for event in module.events.values()
        )
        emit(f"const {module.header}_event_spec: ExtensionEventSpec = .{{")
        with emit.block():
            emit(f".max_event_num = {extension_max_event_num(module)},")
            emit(f".decode = {module.header}.decodeEvent," if has_standard_events else ".decode = null,")
            emit(f".max_xge_event_num = {extension_max_xge_event_num(module)},")
            emit(f".decode_xge = {module.header}.decodeXgeEvent," if has_xge_events else ".decode_xge = null,")
        emit("};")
        emit()

    emit("pub fn eventSpec(extension: extensions.Extension) ?*const ExtensionEventSpec {")
    with emit.block():
        emit("return switch (extension) {")
        with emit.block():
            for module in modules:
                if module.extension_xname is None:
                    emit(f".CORE => &{module.header}_event_spec,")
                else:
                    emit(f".{zig_extension_name(module.extension_xname)} => &{module.header}_event_spec,")
            emit("else => null,")
        emit("};")
    emit("}")
    emit()


def render_global_events(modules: dict[str, ModuleIR]) -> str:
    emit = Emit()
    event_mods = event_modules(modules)
    emit_global_events_prelude(emit, event_mods)
    emit_global_unknown_event(emit)
    emit_global_event_union(emit, event_mods)
    emit_extension_event_specs(emit, event_mods)
    return emit.render()


def error_modules(modules: dict[str, ModuleIR]) -> tuple[ModuleIR, ...]:
    return tuple(module for module in modules.values() if module.core_error_codes is not None)


def emit_global_errors_prelude(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("// zig fmt: off")
    emit("// This file is generated by tools/genproto.py")
    emit()
    emit('const std = @import("std");')
    emit('const extensions = @import("../_ext.zig");')
    for module in modules:
        emit(f'const {module.header} = @import("{module.header}.zig");')
    emit()


def enum_decl_max_value(decl: EnumDecl) -> int:
    return max(item.value for item in decl.items)


def emit_global_protocol_error(emit: Emit) -> None:
    emit("pub const ProtocolError = struct {")
    with emit.block():
        emit("code: u8,")
        emit("sequence: u16,")
        emit("bad_value: u32,")
        emit("minor_opcode: u16,")
        emit("major_opcode: u8,")
        emit("tail: [20]u8,")
    emit("};")
    emit()


def emit_global_tagged_error_union(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("pub const TaggedError = union(enum) {")
    with emit.block():
        core = next(module for module in modules if module.extension_xname is None)
        assert core.core_error_codes is not None
        for item in core.core_error_codes.items:
            emit(f"{item.name}: ProtocolError,")
        for module in modules:
            if module.extension_xname is None or module.core_error_codes is None:
                continue
            for item in module.core_error_codes.items:
                emit(f"{item.name}: ProtocolError,")
        emit("Unknown: ProtocolError,")
        emit("NonX11: anyerror,")
    emit("};")
    emit()


def emit_decode_error_function(emit: Emit, fn_name: str, decl: EnumDecl) -> None:
    emit(f"fn {fn_name}(code: u8, raw: ProtocolError) ?TaggedError {{")
    with emit.block():
        emit("return switch (code) {")
        with emit.block():
            for item in decl.items:
                emit(f'{item.value} => .{{ .{item.name} = raw }},')
            emit("else => null,")
        emit("};")
    emit("}")
    emit()


def emit_extension_error_specs(emit: Emit, modules: tuple[ModuleIR, ...]) -> None:
    emit("pub const ExtensionErrorSpec = struct {")
    with emit.block():
        emit("max_error_num: u8,")
        emit("decode: *const fn (u8, ProtocolError) ?TaggedError,")
    emit("};")
    emit()

    for module in modules:
        if module.core_error_codes is None:
            continue
        emit(f"const {module.header}_error_spec: ExtensionErrorSpec = .{{")
        with emit.block():
            emit(f".max_error_num = {enum_decl_max_value(module.core_error_codes)},")
            if module.extension_xname is None:
                emit(".decode = decodeCoreErrorImpl,")
            else:
                emit(f".decode = decode{zig_extension_prefix(module.header)}Error,")
        emit("};")
        emit()

    emit("pub fn errorSpec(extension: extensions.Extension) ?*const ExtensionErrorSpec {")
    with emit.block():
        emit("return switch (extension) {")
        with emit.block():
            for module in modules:
                if module.core_error_codes is None:
                    continue
                if module.extension_xname is None:
                    emit(f".CORE => &{module.header}_error_spec,")
                else:
                    emit(f".{zig_extension_name(module.extension_xname)} => &{module.header}_error_spec,")
            emit("else => null,")
        emit("};")
    emit("}")
    emit()


def render_global_errors(modules: dict[str, ModuleIR]) -> str:
    emit = Emit()
    mods = error_modules(modules)
    emit_global_errors_prelude(emit, mods)
    emit_global_protocol_error(emit)
    emit_global_tagged_error_union(emit, mods)
    core = next(module for module in mods if module.extension_xname is None)
    assert core.core_error_codes is not None
    emit_decode_error_function(emit, "decodeCoreErrorImpl", core.core_error_codes)
    for module in mods:
        if module.extension_xname is None or module.core_error_codes is None:
            continue
        emit_decode_error_function(
            emit,
            f"decode{zig_extension_prefix(module.header)}Error",
            module.core_error_codes,
        )
    emit("pub fn decodeCoreError(code: u8, raw: ProtocolError) ?TaggedError {")
    with emit.block():
        emit("return decodeCoreErrorImpl(code, raw);")
    emit("}")
    emit()
    emit_extension_error_specs(emit, mods)
    return emit.render()


def load_bindings(path: Path) -> GeneratorInput:
    root = ET.parse(path).getroot()
    bindings = xcbxml.root_item.match(root)
    assert isinstance(bindings, xcbxml.Bindings)
    return GeneratorInput(path=path, bindings=bindings)


def main() -> None:
    resolved_modules: dict[str, ModuleIR] = {}
    for xml_path in XML_PATHS:
        gen_input = load_bindings(xml_path)
        bindings = gen_input.bindings
        module = Resolver(bindings, resolved_modules).resolve_module()
        out_path = OUT_DIR / f"{module.header}.zig"
        out_path.write_text(render_module(module) + "\n")
        resolved_modules[module.header] = module
        print(
            "generated"
            f" file={out_path}"
            f" requests={len(module.requests)}"
            f" structs={len(module.structs)}"
            f" xids={len(module.xidtypes) + len(module.xidunions)}"
            f" enums={len(module.enums)}"
            f" imports={len(module.imports)}"
        )
    events_out_path = OUT_DIR / "events.zig"
    events_out_path.write_text(render_global_events(resolved_modules) + "\n")
    print(f"generated file={events_out_path} modules={len(event_modules(resolved_modules))}")
    errors_out_path = OUT_DIR / "errors.zig"
    errors_out_path.write_text(render_global_errors(resolved_modules) + "\n")
    print(f"generated file={errors_out_path} modules={len(error_modules(resolved_modules))}")


if __name__ == "__main__":
    main()
