from __future__ import annotations

from dataclasses import dataclass, replace

from . import xcbxml
from .common import BaseType, Emit, Size
from .resolver import Resolver
from .simple import EnumType, EnumWireType, SCALAR_TYPES


def make_xid_type(name: str, enums: list[EnumType]) -> BaseType:
    et = EnumType(name.lower().capitalize(), [], exhaustive=False)
    enums.append(et)
    return EnumWireType(et, SCALAR_TYPES['CARD32'])


@dataclass(frozen=True)
class XidUnionType(BaseType):
    name: str
    members: list[EnumWireType]
    module_prefix: str = ''

    @property
    def decl_name(self) -> str:
        return f'{self.module_prefix}{self.name}'

    def with_module_prefix(self, prefix: str) -> XidUnionType:
        return replace(self, module_prefix=prefix)

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
                emit(f'{member.enum_type.name.lower()}: {member.enum_type.name},')
            emit('raw: u32,')
            emit('pub fn toInt(self: @This()) u32 {')
            with emit.block():
                emit('return switch (self) {')
                with emit.block():
                    for member in self.members:
                        emit(f'.{member.enum_type.name.lower()} => |value| @intFromEnum(value),')
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
        members: list[EnumWireType] = []
        for name in xidunion.fields:
            member = resolver.get(name)
            if not isinstance(member, EnumWireType):
                raise NotImplementedError('xidunion members must be xidtypes')
            members.append(member)
        return XidUnionType(
            name=xidunion.name.lower().capitalize(),
            members=members,
        )
