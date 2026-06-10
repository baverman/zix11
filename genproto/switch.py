from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Mapping

from . import xcbxml
from .common import (
    COMMON_ARGS,
    collect_decode_args,
    Emit,
    DecodeScope,
    Field,
    InnerType,
    ordered_decode_args,
    Parent,
    Size,
    emit_decl_items,
    emit_expr,
    expr_refs,
    items_size,
    zig_local_name,
    zig_tag_name,
)
from .fields import build_items
from .list_type import ListType
from .resolver import Resolver
from .simple import EnumType


def decode_scope(items: list[Field], args: Mapping[str, str]) -> DecodeScope:
    return DecodeScope(
        owner_expr='payload',
        local_names=frozenset(
            {
                'switch_value',
                *args,
                *(item.name for item in items if not item.public),
            }
        ),
    )


def replace_field_ref_in_expr(expr: xcbxml.ListExpr, ref: str, ztype: str) -> xcbxml.ListExpr:
    if isinstance(expr, xcbxml.FieldRef) and expr.ref == ref:
        return xcbxml.ParamRef(ref=ref, type=ztype)
    if isinstance(expr, xcbxml.PopCount):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, ztype)
    elif isinstance(expr, xcbxml.SumOf):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, ztype)
    elif isinstance(expr, xcbxml.Op):
        expr.left = replace_field_ref_in_expr(expr.left, ref, ztype)
        expr.right = replace_field_ref_in_expr(expr.right, ref, ztype)
    elif isinstance(expr, xcbxml.Unop):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, ztype)
    return expr


def bind_outer_list_refs(
    list_type: ListType,
    fields_by_name: dict[str, Field],
    seen: set[str | None],
) -> None:
    if list_type.len is None:
        return
    for ref in expr_refs(list_type.len):
        if ref in fields_by_name and ref not in seen:
            seen.add(ref)
            field = fields_by_name[ref]
            list_type.len = replace_field_ref_in_expr(list_type.len, ref, field.type.decl_name)


def switch_decode_signature(args: Mapping[str, str]) -> str:
    result: list[str] = []
    for name, ztype in ordered_decode_args(args).items():
        if name in COMMON_ARGS:
            result.append(f'{name}: {ztype}')
    result.append('switch_value: u32')
    for name, ztype in ordered_decode_args(args).items():
        if name not in COMMON_ARGS:
            result.append(f'{name}: {ztype}')
    return ', '.join(result)


def switch_decode_call_args(
    args: Mapping[str, str], scope: DecodeScope, switch_value: str
) -> list[str]:
    result: list[str] = []
    for name in ordered_decode_args(args):
        if name in COMMON_ARGS:
            result.append(name)
    result.append(switch_value)
    for name in ordered_decode_args(args):
        if name not in COMMON_ARGS:
            result.append(scope.get(name))
    return result


@dataclass(frozen=True)
class CaseArm:
    name: str
    value: int
    items: list[Field]

    @staticmethod
    def from_schema(
        case_item: xcbxml.CaseItem,
        resolver: Resolver,
        parents: tuple[Parent, ...],
        owner_name: str,
    ) -> CaseArm:
        enum_type = resolver.get(case_item.enum_ref[0])
        if not isinstance(enum_type, EnumType):
            raise NotImplementedError('switch/case enumref must reference enum')
        value = None
        for item in enum_type.items:
            if item.name == case_item.enum_ref[1]:
                value = int(item.value)
                break
        if value is None:
            raise NotImplementedError(
                f'unknown enum item: {case_item.enum_ref[0]}.{case_item.enum_ref[1]}'
            )
        return CaseArm(
            name=zig_tag_name(case_item.name or case_item.enum_ref[1]),
            value=value,
            items=build_items(parents, case_item.fields, resolver, owner_name),
        )

    @property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_decl(self, emit: Emit) -> None:
        emit(f'{self.name}: struct {{')
        with emit.block():
            emit_decl_items(emit, self.items)
        emit('},')

    def emit_decode_body(self, emit: Emit, scope: DecodeScope) -> None:
        for item in self.items:
            item.type.emit_decode(emit, item.decode_target_expr('payload'), scope)

    def emit_encode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_encode(emit, item.encode_value_expr('it'))

    def emit_deinit_body(self, emit: Emit, owner: str = 'it') -> None:
        emitted = False
        for item in self.items:
            if item.type.size == 'dyn':
                emitted = True
                item.type.emit_deinit(emit, f'{owner}.{item.name}')
        if not emitted:
            emit(f'_ = {owner};')


@dataclass(frozen=True)
class BitcaseArm:
    name: str
    value: int
    items: list[Field]

    @staticmethod
    def from_schema(
        switch_item: xcbxml.SwitchItem,
        resolver: Resolver,
        parents: tuple[Parent, ...],
        owner_name: str,
    ) -> BitcaseArm:
        enum_type = resolver.get(switch_item.enum_refs[0][0])
        if not isinstance(enum_type, EnumType):
            raise NotImplementedError('switch/bitcase enumref must reference enum')
        value = 0
        for enum_name, item_name in switch_item.enum_refs:
            if enum_name != enum_type.name:
                raise NotImplementedError('switch/bitcase enumrefs must use the same enum')
            for item in enum_type.items:
                if item.name == item_name:
                    value |= int(item.value)
                    break
            else:
                raise NotImplementedError(f'unknown enum item: {enum_name}.{item_name}')
        items = build_items(parents, switch_item.fields, resolver, owner_name)
        if switch_item.name is not None:
            name = switch_item.name
        elif len(items) == 1:
            name = items[0].name
        elif len(switch_item.enum_refs) == 1:
            name = switch_item.enum_refs[0][1]
        else:
            raise NotImplementedError('multi-enumref bitcase requires explicit name')
        return BitcaseArm(
            name=zig_tag_name(name),
            value=value,
            items=items,
        )

    @property
    def size(self) -> Size:
        return items_size(self.items)

    @property
    def is_direct(self) -> bool:
        return len(self.items) == 1 and not isinstance(self.items[0].type, ListType)

    def emit_decl(self, emit: Emit) -> None:
        if self.is_direct:
            item = self.items[0]
            if not item.public:
                raise NotImplementedError('single-item bitcase payload must be public')
            emit(f'{self.name}: ?{item.type.decl_name} = null,')
            return

        emit(f'{self.name}: ?struct {{')
        with emit.block():
            emit_decl_items(emit, self.items)
        emit('} = null,')

    def emit_decode_body(self, emit: Emit, scope: DecodeScope) -> None:
        for item in self.items:
            item.type.emit_decode(emit, item.decode_target_expr('payload'), scope)

    def emit_encode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_encode(emit, item.encode_value_expr('it'))

    def emit_deinit_body(self, emit: Emit, owner: str = 'it') -> None:
        emitted = False
        for item in self.items:
            if item.type.size == 'dyn':
                emitted = True
                item.type.emit_deinit(emit, f'{owner}.{item.name}')
        if not emitted:
            emit(f'_ = {owner};')


@dataclass(frozen=True)
class CaseType(InnerType):
    name: str
    field_name: str
    arms: list[CaseArm]

    @property
    def decl_name(self) -> str:
        return self.name

    @cached_property
    def size(self) -> Size:
        return 'dyn' if any(items_size(arm.items) == 'dyn' for arm in self.arms) else 'fixed'

    def decode_args(self) -> Mapping[str, str]:
        args = dict(super().decode_args())
        for arm in self.arms:
            args.update(collect_decode_args(arm.items))
        return args

    @staticmethod
    def from_schema(
        case_switch: xcbxml.CaseSwitchField,
        resolver: Resolver,
        parents: tuple[Parent, ...],
        owner_name: str,
    ) -> CaseType:
        arms = []
        for case_item in case_switch.items:
            arms.append(CaseArm.from_schema(case_item, resolver, (case_switch,), owner_name))

        return CaseType(
            name=case_switch.name[:1].upper() + case_switch.name[1:],
            field_name=case_switch.fieldref.ref,
            arms=arms,
        )

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str, scope: DecodeScope) -> None:
        switch_value = f'@intFromEnum({zig_local_name(self.field_name)})'
        owner_expr = value_expr.rpartition('.')[0]
        type_ref = f'@TypeOf({owner_expr}).{self.name}'
        args = ', '.join(switch_decode_call_args(self.decode_args(), scope, switch_value))
        emit(f'{value_expr} = try {type_ref}.decode({args});')

    def update_fieldref(
        self, parents: tuple[Parent, ...], field: Field, fields_by_name: dict[str, Field]
    ) -> None:
        discrim_field = fields_by_name[self.field_name]
        discrim_field.public = False
        discrim_field.encode_value_expr_ = (
            f'@as({discrim_field.type.decl_name}, '
            f'@enumFromInt({{owner}}.{field.name}.switchValue()))'
        )
        seen: set[str | None] = {self.field_name}
        for arm in self.arms:
            for it in arm.items:
                if isinstance(it.type, ListType):
                    bind_outer_list_refs(it.type, fields_by_name, seen)

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = union(enum) {{')
        with emit.block():
            for arm in self.arms:
                arm.emit_decl(emit)
            emit()
            emit('pub fn encode(self: *const @This(), writer: *std.Io.Writer) !void {')
            with emit.block():
                emit('switch (self.*) {')
                with emit.block():
                    for arm in self.arms:
                        emit(f'.{arm.name} => |it| {{')
                        with emit.block():
                            arm.emit_encode_body(emit)
                        emit('},')
                emit('}')
            emit('}')
            emit()
            emit('pub fn switchValue(self: *const @This()) u32 {')
            with emit.block():
                emit('return switch (self.*) {')
                with emit.block():
                    for arm in self.arms:
                        emit(f'.{arm.name} => {arm.value},')
                emit('};')
            emit('}')
            emit()
            emit(f'pub fn decode({switch_decode_signature(self.decode_args())}) !@This() {{')
            with emit.block():
                emit('return switch (switch_value) {')
                with emit.block():
                    for i, arm in enumerate(self.arms):
                        emit(f'{arm.value} => blk: {{')
                        with emit.block():
                            emit(
                                f'var payload: @typeInfo(@This()).@"union".fields[{i}].type = undefined;'
                            )
                            arm.emit_decode_body(emit, decode_scope(arm.items, self.decode_args()))
                            emit(f'break :blk .{{ .{arm.name} = payload }};')
                        emit('},')
                    emit('else => return error.UnexpectedSwitchTag,')
                emit('};')
            emit('}')
            if self.size == 'dyn':
                emit()
                emit('pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {')
                with emit.block():
                    emit('switch (self.*) {')
                    with emit.block():
                        for arm in self.arms:
                            emit(f'.{arm.name} => |*payload| {{')
                            with emit.block():
                                arm.emit_deinit_body(emit, 'payload')
                            emit('},')
                    emit('}')
                emit('}')
        emit('};')


@dataclass(frozen=True)
class BitcaseType(InnerType):
    name: str
    expr: xcbxml.ListExpr
    arms: list[BitcaseArm]

    @property
    def decl_name(self) -> str:
        return self.name

    @property
    def field_name(self) -> str | None:
        return self.expr.ref if isinstance(self.expr, xcbxml.FieldRef) else None

    @cached_property
    def size(self) -> Size:
        return 'dyn' if any(arm.size == 'dyn' for arm in self.arms) else 'fixed'

    def decode_args(self) -> Mapping[str, str]:
        args = dict(super().decode_args())
        for arm in self.arms:
            args.update(collect_decode_args(arm.items))
        return args

    @staticmethod
    def from_schema(
        switch: xcbxml.SwitchField,
        resolver: Resolver,
        parents: tuple[Parent, ...],
        owner_name: str,
    ) -> BitcaseType:
        arms = []
        for switch_item in switch.items:
            arms.append(BitcaseArm.from_schema(switch_item, resolver, (switch,), owner_name))

        return BitcaseType(
            name=switch.name[:1].upper() + switch.name[1:],
            expr=switch.expr,
            arms=arms,
        )

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str, scope: DecodeScope) -> None:
        owner_expr = value_expr.rpartition('.')[0]
        if self.field_name is not None:
            switch_value = zig_local_name(self.field_name)
        else:
            switch_value = emit_expr(self.expr, f'{owner_expr}.')
        type_ref = f'@TypeOf({owner_expr}).{self.name}'
        args = ', '.join(switch_decode_call_args(self.decode_args(), scope, switch_value))
        emit(f'{value_expr} = try {type_ref}.decode({args});')

    def update_fieldref(
        self, parents: tuple[Parent, ...], field: Field, fields_by_name: dict[str, Field]
    ) -> None:
        if self.field_name is not None:
            mask_field = fields_by_name[self.field_name]
            mask_field.public = False
            mask_field.encode_value_expr_ = f'@intCast({{owner}}.{field.name}.switchValue())'
        seen: set[str | None] = {self.field_name} if self.field_name else set()
        for arm in self.arms:
            for it in arm.items:
                if isinstance(it.type, ListType):
                    bind_outer_list_refs(it.type, fields_by_name, seen)

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            for arm in self.arms:
                arm.emit_decl(emit)

            emit()
            emit('pub fn encode(self: *const @This(), writer: *std.Io.Writer) !void {')
            with emit.block():
                for arm in self.arms:
                    emit(f'if (self.{arm.name}) |it| {{')
                    with emit.block():
                        if arm.is_direct:
                            arm.items[0].type.emit_encode(emit, 'it')
                        else:
                            arm.emit_encode_body(emit)
                    emit('}')
            emit('}')

            emit()
            emit('pub fn switchValue(self: *const @This()) u32 {')
            with emit.block():
                emit('var result: u32 = 0;')
                for arm in self.arms:
                    emit(f'if (self.{arm.name} != null) result |= {arm.value};')
                emit('return result;')
            emit('}')

            emit()
            emit(f'pub fn decode({switch_decode_signature(self.decode_args())}) !@This() {{')
            with emit.block():
                emit('var result: @This() = .{};')
                for i, arm in enumerate(self.arms):
                    emit(f'if ((switch_value & {arm.value}) != 0) {{')
                    with emit.block():
                        if arm.is_direct:
                            item = arm.items[0]
                            if not item.public:
                                raise NotImplementedError(
                                    'single-item bitcase payload must be public'
                                )
                            item.type.emit_decode(
                                emit, f'const {arm.name}', decode_scope(arm.items, self.decode_args())
                            )
                            emit(f'result.{arm.name} = {arm.name};')
                        else:
                            emit(
                                f'var payload: @typeInfo(@TypeOf(result.{arm.name})).optional.child = undefined;'
                            )
                            arm.emit_decode_body(emit, decode_scope(arm.items, self.decode_args()))
                            emit(f'result.{arm.name} = payload;')
                    emit('}')
                emit('return result;')
            emit('}')

            if self.size == 'dyn':
                emit()
                emit('pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {')
                with emit.block():
                    for arm in self.arms:
                        if arm.size != 'dyn':
                            continue
                        emit(f'if (self.{arm.name}) |*payload| {{')
                        with emit.block():
                            if arm.is_direct:
                                arm.items[0].type.emit_deinit(emit, 'payload')
                            else:
                                arm.emit_deinit_body(emit, 'payload')
                        emit('}')
                emit('}')
        emit('};')
