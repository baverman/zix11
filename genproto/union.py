from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property

from . import xcbxml
from .common import BaseType, DecodeScope, Emit, Field, Size
from .fields import build_items
from .resolver import Resolver


@dataclass(frozen=True)
class UnionType(BaseType):
    name: str
    items: list[Field]
    module_prefix: str = ''

    @property
    def decl_name(self) -> str:
        return f'{self.module_prefix}{self.name}'

    def with_module_prefix(self, prefix: str) -> UnionType:
        return replace(self, module_prefix=prefix)

    @cached_property
    def size(self) -> Size:
        return max(item.type.size for item in self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str, scope: DecodeScope) -> None:
        _ = scope
        emit(f'{value_expr} = try {self.decl_name}.decode(reader);')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            emit(f'raw: [{self.size}]u8,')
            emit()

            emit(f'pub fn fromRaw(raw: [{self.size}]u8) @This() {{')
            with emit.block():
                emit('return .{ .raw = raw };')
            emit('}')
            emit()

            emit(f'pub fn asRaw(self: @This()) [{self.size}]u8 {{')
            with emit.block():
                emit('return self.raw;')
            emit('}')
            emit()

            emit('pub fn encode(self: @This(), writer: *std.Io.Writer) errors.EncodeError!void {')
            with emit.block():
                emit('try writer.writeAll(self.raw[0..]);')
            emit('}')
            emit()

            emit('pub fn decode(reader: *std.Io.Reader) errors.DecodeError!@This() {')
            with emit.block():
                emit(f'var raw: [{self.size}]u8 = undefined;')
                emit(f'@memcpy(raw[0..], try reader.take({self.size}));')
                emit('return .{ .raw = raw };')
            emit('}')

            for item in self.items:
                suffix = item.name[:1].upper() + item.name[1:]
                emit()
                emit(
                    f'pub fn from{suffix}(value: {item.type.decl_name}) errors.EncodeError!@This() {{'
                )
                with emit.block():
                    emit(f'var raw = std.mem.zeroes([{self.size}]u8);')
                    emit('var writer_impl: std.Io.Writer = .fixed(&raw);')
                    emit('const writer = &writer_impl;')
                    item.type.emit_encode(emit, 'value')
                    emit('return .{ .raw = raw };')
                emit('}')
                emit()

                emit(
                    f'pub fn as{suffix}(self: @This()) errors.DecodeError!{item.type.decl_name} {{'
                )
                with emit.block():
                    emit('var reader_impl: std.Io.Reader = .fixed(&self.raw);')
                    emit('const reader = &reader_impl;')
                    emit(f'var value: {item.type.decl_name} = undefined;')
                    item.type.emit_decode(emit, 'value', DecodeScope.empty())
                    emit('return value;')
                emit('}')
        emit('};')

    @staticmethod
    def from_schema(union: xcbxml.Union, resolver: Resolver) -> UnionType:
        items = build_items((union,), union.fields, resolver, union.name)
        if not items:
            raise NotImplementedError('empty unions are not supported')
        if any(not isinstance(item.type.size, int) for item in items):
            raise NotImplementedError('only unions with exact integer item sizes are supported')
        return UnionType(name=union.name, items=items)
