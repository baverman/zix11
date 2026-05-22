from __future__ import annotations

from dataclasses import dataclass

from . import xcbxml
from .common import BaseType, Emit, Resolver, Size


@dataclass(frozen=True)
class XidType(BaseType):
    name: str

    @property
    def decl_name(self) -> str:
        return self.name

    @property
    def size(self) -> Size:
        return 4

    def coerce_to_raw(self, value_expr: str) -> str:
        return f'@intFromEnum({value_expr})'

    def coerce_from_raw(self, value_expr: str) -> str:
        return f'@as({self.name}, @enumFromInt({value_expr}))'

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'writer.writeInt(u32, {self.coerce_to_raw(value_expr)});')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        emit(f'{value_expr} = {self.coerce_from_raw("try reader.takeInt(u32, .native)")};')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = enum(u32) {{')
        with emit.block():
            emit('_,')
        emit('};')
        emit()

    @staticmethod
    def from_schema(xidtype: xcbxml.XidType) -> XidType:
        return XidType(name=xidtype.name.lower().capitalize())


@dataclass(frozen=True)
class XidUnionType(BaseType):
    name: str
    members: tuple[XidType, ...]

    @property
    def decl_name(self) -> str:
        return self.name

    @property
    def size(self) -> Size:
        return 4

    def coerce_to_raw(self, value_expr: str) -> str:
        return f'{value_expr}.toInt()'

    def coerce_from_raw(self, value_expr: str) -> str:
        return f'.{{ .raw = {value_expr} }}'

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'writer.writeInt(u32, {self.coerce_to_raw(value_expr)});')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        emit(f'{value_expr} = {self.coerce_from_raw("try reader.takeInt(u32, .native)")};')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = union(enum) {{')
        with emit.block():
            for member in self.members:
                emit(f'{member.name.lower()}: {member.name},')
            emit('raw: u32,')
            emit('pub fn toInt(self: @This()) u32 {')
            with emit.block():
                emit('return switch (self) {')
                with emit.block():
                    for member in self.members:
                        emit(f'.{member.name.lower()} => |value| @intFromEnum(value),')
                    emit('.raw => |value| value,')
                emit('};')
            emit('}')
            emit()
            emit('pub fn encode(self: @This(), writer: anytype) void {')
            with emit.block():
                emit('writer.writeInt(u32, self.toInt());')
            emit('}')
            emit()
            emit('pub fn decode(reader: *std.Io.Reader) !@This() {')
            with emit.block():
                emit('return .{ .raw = try reader.takeInt(u32, .native) };')
            emit('}')
        emit('};')
        emit()

    @staticmethod
    def from_schema(xidunion: xcbxml.XidUnion, resolver: Resolver) -> XidUnionType:
        members: list[XidType] = []
        for name in xidunion.fields:
            member = resolver.get(name)
            if not isinstance(member, XidType):
                raise NotImplementedError('xidunion members must be xidtypes')
            members.append(member)
        return XidUnionType(
            name=xidunion.name.lower().capitalize(),
            members=tuple(members),
        )
