from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import xcbxml
from .common import (
    BaseType,
    Emit,
    Field,
    Resolver,
    Size,
    emit_decl_items,
    emit_decode_fn,
    emit_deinit_fn,
    emit_encode_fn,
    items_size,
)
from .fields import build_items


@dataclass(frozen=True)
class StructType(BaseType):
    name: str
    items: tuple[Field, ...]

    @staticmethod
    def from_schema(struct: xcbxml.Struct, resolver: Resolver) -> StructType:
        result = StructType(
            name=struct.name, items=build_items(struct.fields, resolver, struct.name)
        )
        resolver.set(struct.name, result)
        return result

    @property
    def decl_name(self) -> str:
        return self.name

    @cached_property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr} = try {self.name}.decode(allocator, reader);')
        else:
            emit(f'{value_expr} = try {self.name}.decode(reader);')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            emit_decl_items(emit, self.items)
            emit_encode_fn(emit, self.items)
            emit_decode_fn(emit, self.size == 'dyn', self.items)
            emit_deinit_fn(emit, self.size == 'dyn', self.items)
        emit('};')
        emit()
