from __future__ import annotations

from dataclasses import dataclass

from . import xcbxml
from .common import BaseType, Emit, Size


@dataclass(frozen=True)
class ScalarType(BaseType):
    x_name: str
    name: str
    _size: Size

    @property
    def size(self) -> Size:
        return self._size

    @property
    def decl_name(self) -> str:
        return self.name

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        if self.name == 'bool':
            emit(f'writer.writeByte(@intFromBool({value_expr}));')
        elif self.name == 'u8':
            emit(f'writer.writeByte({value_expr});')
        else:
            emit(f'writer.writeInt({self.name}, {value_expr});')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        if self.name == 'bool':
            emit(f'{value_expr} = (try reader.takeByte()) != 0;')
        elif self.name == 'u8':
            emit(f'{value_expr} = try reader.takeByte();')
        else:
            emit(f'{value_expr} = try reader.takeInt({self.name}, .native);')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr


@dataclass(frozen=True)
class PadType(BaseType):
    decl_name = '_pad_'
    byte_count: int

    @property
    def size(self) -> Size:
        return self.byte_count

    def emit_encode(self, emit: Emit, _expr: str) -> None:
        emit(f'writer.splatByte(0, {self.byte_count});')

    def emit_decode(self, emit: Emit, _expr: str) -> None:
        emit(f'_ = try reader.take({self.byte_count});')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr


SCALAR_TYPES: dict[str, ScalarType] = {
    'BOOL': ScalarType('BOOL', 'bool', 1),
    'BYTE': ScalarType('BYTE', 'u8', 1),
    'CARD8': ScalarType('CARD8', 'u8', 1),
    'CARD16': ScalarType('CARD16', 'u16', 2),
    'CARD32': ScalarType('CARD32', 'u32', 4),
    'INT8': ScalarType('INT8', 'i8', 1),
    'INT16': ScalarType('INT16', 'i16', 2),
    'INT32': ScalarType('INT32', 'i32', 4),
}


@dataclass
class EnumType(BaseType):
    name: str
    scalar_type: ScalarType | None
    items: tuple[xcbxml.EnumItem, ...]

    @property
    def decl_name(self) -> str:
        return self.name

    @property
    def size(self) -> Size:
        assert self.scalar_type
        return self.scalar_type.size

    @staticmethod
    def from_schema(enum: xcbxml.Enum) -> EnumType:
        return EnumType(
            name=enum.name,
            scalar_type=None,
            items=tuple(enum.fields),
        )

    def bind_scalar_type(self, scalar_type: ScalarType) -> None:
        if self.scalar_type is None:
            self.scalar_type = scalar_type
        elif self.scalar_type != scalar_type:
            raise NotImplementedError(
                f'enum {self.name} used with multiple scalar types: {self.scalar_type.x_name} and {scalar_type.x_name}'
            )

    def coerce_to_raw(self, value_expr: str) -> str:
        return f'@intFromEnum({value_expr})'

    def coerce_from_raw(self, value_expr: str) -> str:
        return f'@as({self.name}, @enumFromInt({value_expr}))'

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        assert self.scalar_type
        self.scalar_type.emit_encode(emit, self.coerce_to_raw(value_expr))

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        assert self.scalar_type
        if self.scalar_type.name == 'u8':
            emit(f'{value_expr} = {self.coerce_from_raw("try reader.takeByte()")};')
        else:
            emit(
                f'{value_expr} = {self.coerce_from_raw(f"try reader.takeInt({self.scalar_type.name}, .native)")};'
            )

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        if self.scalar_type is None:
            raise NotImplementedError(f'cannot infer scalar type for enum: {self.name}')
        emit(f'pub const {self.name} = enum({self.scalar_type.name}) {{')
        with emit.block():
            for item in self.items:
                emit(f'{item.name} = {item.value},')
        emit('};')
        emit()
