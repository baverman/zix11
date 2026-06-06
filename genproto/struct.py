from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property

from . import xcbxml
from .common import (
    BaseType,
    Emit,
    Field,
    Size,
    emit_decl_items,
    emit_decode_fn,
    emit_deinit_fn,
    emit_encode_fn,
    items_size,
)
from .fields import build_items, collect_decode_params
from .resolver import Resolver


@dataclass(frozen=True)
class StructType(BaseType):
    name: str
    items: list[Field]
    module_prefix: str = ''
    decode_params: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def from_schema(struct: xcbxml.Struct, resolver: Resolver) -> StructType:
        items = build_items((struct,), struct.fields, resolver, struct.name)
        result = StructType(
            name=struct.name,
            items=items,
            decode_params=collect_decode_params(items, resolver),
        )
        resolver.set(struct.name, result)
        return result

    @property
    def decl_name(self) -> str:
        return f'{self.module_prefix}{self.name}'

    def with_module_prefix(self, prefix: str) -> StructType:
        return replace(self, module_prefix=prefix)

    @cached_property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'try {value_expr}.encode(writer);')

    def emit_decode(self, emit: Emit, value_expr: str, decode_args: str = '') -> None:
        if self.size == 'dyn':
            emit(f'{value_expr} = try {self.decl_name}.decode(allocator, reader{decode_args});')
        else:
            emit(f'{value_expr} = try {self.decl_name}.decode(reader{decode_args});')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        if self.size == 'dyn':
            emit(f'{value_expr}.deinit(allocator);')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            emit_decl_items(emit, self.items)
            emit_encode_fn(emit, self.items)
            emit_decode_fn(
                emit,
                self.size == 'dyn',
                self.items,
                args=tuple(f'{name}: {ztype}' for name, ztype in self.decode_params),
            )
            emit_deinit_fn(emit, self.size == 'dyn', self.items)
        emit('};')
        emit()
