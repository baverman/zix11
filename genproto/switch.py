from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import xcbxml
from .common import Emit, Field, InnerType, Resolver, Size, emit_decl_items, items_size
from .fields import build_items
from .simple import EnumType


@dataclass(frozen=True)
class CaseArm:
    name: str
    value: int
    items: tuple[Field, ...]

    @staticmethod
    def from_schema(
        case_item: xcbxml.CaseItem,
        resolver: Resolver,
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
            name=case_item.name or case_item.enum_ref[1],
            value=value,
            items=build_items(case_item.fields, resolver, owner_name),
        )

    @property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_decl(self, emit: Emit) -> None:
        emit(f'{self.name}: struct {{')
        with emit.block():
            emit_decl_items(emit, self.items)
        emit('},')

    def emit_decode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_decode(emit, item.decode_target_expr('payload'))

    def emit_encode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_encode(emit, item.encode_value_expr('it'))

    def emit_deinit_body(self, emit: Emit) -> None:
        emitted = False
        for item in self.items:
            if item.type.size == 'dyn':
                emitted = True
                item.type.emit_deinit(emit, f'it.{item.name}')
        if not emitted:
            emit('_ = it;')


@dataclass(frozen=True)
class BitcaseArm:
    name: str
    value: int
    items: tuple[Field, ...]

    @staticmethod
    def from_schema(
        switch_item: xcbxml.SwitchItem,
        resolver: Resolver,
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
        if switch_item.name is not None:
            name = switch_item.name
        elif len(switch_item.enum_refs) == 1:
            name = switch_item.enum_refs[0][1]
        else:
            raise NotImplementedError('multi-enumref bitcase requires explicit name')
        return BitcaseArm(
            name=name,
            value=value,
            items=build_items(switch_item.fields, resolver, owner_name),
        )

    @property
    def size(self) -> Size:
        return items_size(self.items)

    @property
    def is_direct(self) -> bool:
        return len(self.items) == 1

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

    def emit_decode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_decode(emit, item.decode_target_expr('payload'))

    def emit_encode_body(self, emit: Emit) -> None:
        for item in self.items:
            item.type.emit_encode(emit, item.encode_value_expr('it'))

    def emit_deinit_body(self, emit: Emit) -> None:
        emitted = False
        for item in self.items:
            if item.type.size == 'dyn':
                emitted = True
                item.type.emit_deinit(emit, f'it.{item.name}')
        if not emitted:
            emit('_ = it;')


@dataclass(frozen=True)
class CaseType(InnerType):
    name: str
    field_name: str
    arms: tuple[CaseArm, ...]

    @property
    def decl_name(self) -> str:
        return self.name

    @cached_property
    def size(self) -> Size:
        return 'dyn' if any(items_size(arm.items) == 'dyn' for arm in self.arms) else 'fixed'

    @staticmethod
    def from_schema(
        case_switch: xcbxml.CaseSwitchField,
        resolver: Resolver,
        owner_name: str,
    ) -> CaseType:
        arms = []
        for case_item in case_switch.items:
            arms.append(CaseArm.from_schema(case_item, resolver, owner_name))

        return CaseType(
            name=case_switch.name[:1].upper() + case_switch.name[1:],
            field_name=case_switch.fieldref.ref,
            arms=tuple(arms),
        )

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        switch_value = f'@intFromEnum({self.field_name})'
        if self.size == 'dyn':
            emit(f'{value_expr} = try {self.name}.decode(allocator, reader, {switch_value});')
        else:
            emit(f'{value_expr} = try {self.name}.decode(reader, {switch_value});')

    def update_fieldref(self, field: Field, fields_by_name: dict[str, Field]) -> None:
        discrim_field = fields_by_name[self.field_name]
        discrim_field.public = False
        discrim_field.encode_value_expr_ = (
            f'@as({discrim_field.type.decl_name}, '
            f'@enumFromInt({{owner}}.{field.name}.switchValue()))'
        )

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = union(enum) {{')
        with emit.block():
            for arm in self.arms:
                arm.emit_decl(emit)
            emit()
            emit('pub fn encode(self: *const @This(), writer: anytype) !void {')
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
            if self.size == 'dyn':
                emit(
                    'pub fn decode(allocator: std.mem.Allocator, reader: *std.Io.Reader, switch_value: u32) !@This() {'
                )
            else:
                emit('pub fn decode(reader: *std.Io.Reader, switch_value: u32) !@This() {')
            with emit.block():
                emit('return switch (switch_value) {')
                with emit.block():
                    for i, arm in enumerate(self.arms):
                        emit(f'{arm.value} => blk: {{')
                        with emit.block():
                            emit(
                                f'var payload: @typeInfo(@This()).@"union".fields[{i}].type = undefined;'
                            )
                            arm.emit_decode_body(emit)
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
                            emit(f'.{arm.name} => |*it| {{')
                            with emit.block():
                                arm.emit_deinit_body(emit)
                            emit('},')
                    emit('}')
                emit('}')
        emit('};')


@dataclass(frozen=True)
class BitcaseType(InnerType):
    name: str
    field_name: str
    arms: tuple[BitcaseArm, ...]

    @property
    def decl_name(self) -> str:
        return self.name

    @cached_property
    def size(self) -> Size:
        return 'dyn' if any(arm.size == 'dyn' for arm in self.arms) else 'fixed'

    @staticmethod
    def from_schema(
        switch: xcbxml.SwitchField,
        resolver: Resolver,
        owner_name: str,
    ) -> BitcaseType:
        if not isinstance(switch.expr, xcbxml.FieldRef):
            raise NotImplementedError('switch/bitcase only supports fieldref discriminators')
        arms = []
        for switch_item in switch.items:
            arms.append(BitcaseArm.from_schema(switch_item, resolver, owner_name))

        return BitcaseType(
            name=switch.name[:1].upper() + switch.name[1:],
            field_name=switch.expr.ref,
            arms=tuple(arms),
        )

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        switch_value = self.field_name
        if self.size == 'dyn':
            emit(f'{value_expr} = try {self.name}.decode(allocator, reader, {switch_value});')
        else:
            emit(f'{value_expr} = try {self.name}.decode(reader, {switch_value});')

    def update_fieldref(self, field: Field, fields_by_name: dict[str, Field]) -> None:
        mask_field = fields_by_name[self.field_name]
        mask_field.public = False
        mask_field.encode_value_expr_ = f'@intCast({{owner}}.{field.name}.switchValue())'

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            for arm in self.arms:
                arm.emit_decl(emit)
            emit()
            emit('pub fn encode(self: *const @This(), writer: anytype) !void {')
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
            if self.size == 'dyn':
                emit(
                    'pub fn decode(allocator: std.mem.Allocator, reader: *std.Io.Reader, switch_value: u32) !@This() {'
                )
            else:
                emit('pub fn decode(reader: *std.Io.Reader, switch_value: u32) !@This() {')
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
                            item.type.emit_decode(emit, f'const {arm.name}')
                            emit(f'result.{arm.name} = {arm.name};')
                        else:
                            emit(
                                f'var payload: @typeInfo(@TypeOf(result.{arm.name})).optional.child = undefined;'
                            )
                            arm.emit_decode_body(emit)
                            emit(f'result.{arm.name} = payload;')
                    emit('}')
                emit('return result;')
            emit('}')
            if self.size == 'dyn':
                emit()
                emit('pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {')
                with emit.block():
                    for arm in self.arms:
                        emit(f'if (self.{arm.name}) |*it| {{')
                        with emit.block():
                            if arm.is_direct:
                                arm.items[0].type.emit_deinit(emit, 'it')
                            else:
                                arm.emit_deinit_body(emit)
                        emit('}')
                emit('}')
        emit('};')
