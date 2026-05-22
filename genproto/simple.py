from __future__ import annotations

from dataclasses import dataclass, replace

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


@dataclass(frozen=True)
class AlignPadType(BaseType):
    decl_name = '_pad_'
    alignment: int

    @property
    def size(self) -> Size:
        return 'fixed'

    def emit_encode(self, emit: Emit, _expr: str) -> None:
        emit(f'writer.splatByte(0, wire.pad(writer.seek, {self.alignment}));')

    def emit_decode(self, emit: Emit, _expr: str) -> None:
        emit(f'_ = try reader.take(wire.pad(reader.seek, {self.alignment}));')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr


@dataclass(frozen=True)
class RequiredStartAlignType(BaseType):
    decl_name = '_pad_'
    alignment: int
    offset: int

    @property
    def size(self) -> Size:
        return 'fixed'

    def emit_encode(self, emit: Emit, _expr: str) -> None:
        emit(f'writer.splatByte(0, wire.pad(writer.seek + {self.offset}, {self.alignment}));')

    def emit_decode(self, emit: Emit, _expr: str) -> None:
        emit(f'_ = try reader.take(wire.pad(reader.seek + {self.offset}, {self.alignment}));')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr


SCALAR_TYPES: dict[str, ScalarType] = {
    'BOOL': ScalarType('BOOL', 'bool', 1),
    'BYTE': ScalarType('BYTE', 'u8', 1),
    'CARD8': ScalarType('CARD8', 'u8', 1),
    'char': ScalarType('char', 'u8', 1),
    'void': ScalarType('void', 'u8', 1),
    'CARD16': ScalarType('CARD16', 'u16', 2),
    'CARD32': ScalarType('CARD32', 'u32', 4),
    'INT8': ScalarType('INT8', 'i8', 1),
    'INT16': ScalarType('INT16', 'i16', 2),
    'INT32': ScalarType('INT32', 'i32', 4),
}


@dataclass
class EnumType(BaseType):
    name: str
    items: list[xcbxml.EnumItem]
    exhaustive: bool = True
    module_prefix: str = ''

    @property
    def decl_name(self) -> str:
        return f'{self.module_prefix}{self.name}'

    def with_module_prefix(self, prefix: str) -> EnumType:
        return replace(self, module_prefix=prefix)

    @property
    def size(self) -> Size:
        return 'fixed'

    @staticmethod
    def from_schema(enum: xcbxml.Enum) -> EnumType:
        return EnumType(
            name=enum.name,
            items=list(enum.fields),
        )

    def add_items_from_schema(self, enum: xcbxml.Enum) -> None:
        self.items.extend(enum.fields)

    def coerce_to_raw(self, value_expr: str) -> str:
        return f'@intFromEnum({value_expr})'

    def coerce_from_raw(self, value_expr: str) -> str:
        return f'@as({self.decl_name}, @enumFromInt({value_expr}))'

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError('enum wire width must be provided by the use site')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError('enum wire width must be provided by the use site')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = enum(u32) {{')
        with emit.block():
            values: dict[int, str] = {}
            aliases: list[tuple[str, int]] = []
            for item in self.items:
                if item.name.isdigit():
                    name = f'@"{item.name}"'
                else:
                    name = item.name[0].upper() + item.name[1:]
                value = int(item.value)
                if value in values:
                    aliases.append((name, value))
                    continue
                values[value] = name
                emit(f'{name} = {item.value},')
            if not self.exhaustive:
                emit('_,')
            if aliases:
                emit()
                for name, value in aliases:
                    emit(f'pub const {name}: @This() = @enumFromInt({value});')
        emit('};')
        emit()


@dataclass(frozen=True)
class EnumWireType(BaseType):
    enum_type: EnumType
    scalar_type: ScalarType

    @property
    def decl_name(self) -> str:
        return self.enum_type.decl_name

    @property
    def size(self) -> Size:
        return self.scalar_type.size

    def coerce_to_raw(self, value_expr: str) -> str:
        return f'@intCast({self.enum_type.coerce_to_raw(value_expr)})'

    def coerce_from_raw(self, value_expr: str) -> str:
        return self.enum_type.coerce_from_raw(value_expr)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        self.scalar_type.emit_encode(emit, self.coerce_to_raw(value_expr))

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        if self.scalar_type.name == 'u8':
            emit(f'{value_expr} = {self.coerce_from_raw("try reader.takeByte()")};')
        else:
            emit(
                f'{value_expr} = {self.coerce_from_raw(f"try reader.takeInt({self.scalar_type.name}, .native)")};'
            )

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr
