from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import xcbxml
from .common import BaseType, Emit, Field, Resolver, Size
from .fields import build_items


@dataclass(frozen=True)
class UnionType(BaseType):
    name: str
    items: tuple[Field, ...]

    @property
    def decl_name(self) -> str:
        return self.name

    @cached_property
    def size(self) -> Size:
        return max(item.type.size for item in self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        emit(f'{value_expr} = try {self.name}.decode(reader);')

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
            emit('pub fn encode(self: @This(), writer: anytype) !void {')
            with emit.block():
                emit('writer.write(self.raw[0..]);')
            emit('}')
            emit()
            emit('pub fn decode(reader: *std.Io.Reader) !@This() {')
            with emit.block():
                emit(f'var raw: [{self.size}]u8 = undefined;')
                emit(f'@memcpy(raw[0..], try reader.take({self.size}));')
                emit('return .{ .raw = raw };')
            emit('}')
            for item in self.items:
                suffix = item.name[:1].upper() + item.name[1:]
                emit()
                emit(f'pub fn from{suffix}(value: {item.type.decl_name}) @This() {{')
                with emit.block():
                    emit(f'var raw = std.mem.zeroes([{self.size}]u8);')
                    emit('var writer = io.FixedBufferWriter.init(&raw);')
                    item.type.emit_encode(emit, 'value')
                    emit('return .{ .raw = raw };')
                emit('}')
                emit()
                emit(f'pub fn as{suffix}(self: @This()) !{item.type.decl_name} {{')
                with emit.block():
                    emit('var reader: std.Io.Reader = .fixed(&self.raw);')
                    emit(f'var value: {item.type.decl_name} = undefined;')
                    item.type.emit_decode(emit, 'value')
                    emit('return value;')
                emit('}')
        emit('};')
        emit()

    @staticmethod
    def from_schema(union: xcbxml.Union, resolver: Resolver) -> UnionType:
        items = build_items(union.fields, resolver, union.name)
        if not items:
            raise NotImplementedError('empty unions are not supported')
        if any(not isinstance(item.type.size, int) for item in items):
            raise NotImplementedError('only unions with exact integer item sizes are supported')
        return UnionType(name=union.name, items=items)
