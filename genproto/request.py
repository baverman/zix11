from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import xcbxml
from .common import (
    BaseType,
    Emit,
    Field,
    InjectedType,
    Resolver,
    Size,
    emit_decl_items,
    emit_decode_fn,
    emit_deinit_fn,
    emit_encode_fn,
    items_size,
)
from .fields import build_items, get_byte_slot


@dataclass(frozen=True)
class RequestType:
    name: str
    opcode: int
    byte_slot: Field | None
    items: tuple[Field, ...]
    reply: ReplyType | None

    @staticmethod
    def from_schema(request: xcbxml.Request, resolver: Resolver) -> RequestType:
        items = build_items(request.fields, resolver, request.name)

        return RequestType(
            name=request.name,
            opcode=int(request.opcode),
            byte_slot=get_byte_slot(items),
            items=items,
            reply=None
            if request.reply is None
            else ReplyType.from_schema(request.name, request.reply, resolver),
        )

    def emit_header_byte1(self, emit: Emit) -> None:
        emit('pub fn headerByte1(self: *const @This()) u8 {')
        with emit.block():
            if self.byte_slot and self.byte_slot.public:
                expr = self.byte_slot.type.coerce_to_raw(f'self.{self.byte_slot.name}')
                emit(f'return {expr};')
            else:
                emit('_ = self;')
                emit('return 0;')
        emit('}')

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        encode_items = [it for it in self.items if it is not self.byte_slot]
        with emit.block():
            emit(f'pub const opcode: u8 = {self.opcode};')

            emit()
            emit_decl_items(emit, self.items)

            if self.reply:
                emit()
                self.reply.emit_definition(emit)

            emit()
            self.emit_header_byte1(emit)

            emit_encode_fn(emit, encode_items)
        emit('};')
        emit()


@dataclass(frozen=True)
class ReplyType(BaseType):
    byte_slot: Field | None
    items: tuple[Field, ...]

    @staticmethod
    def from_schema(request_name: str, reply: xcbxml.Reply, resolver: Resolver) -> ReplyType:
        items = build_items(reply.fields, resolver, f'{request_name}Reply')
        byte_slot = get_byte_slot(items)
        if byte_slot:
            if byte_slot.public:
                items = (
                    Field(
                        name=byte_slot.name,
                        type=InjectedType(arg_name=byte_slot.name, base_type=byte_slot.type),
                    ),
                    *items[1:],
                )
            else:
                items = items[1:]

        return ReplyType(
            byte_slot=byte_slot,
            items=items,
        )

    @property
    def decl_name(self) -> str:
        return 'Reply'

    @cached_property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_decode(self, emit: Emit, var_decl: str) -> None:
        raise NotImplementedError

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_definition(self, emit: Emit) -> None:
        emit('pub const Reply = struct {')
        argname = self.byte_slot.name if self.byte_slot and self.byte_slot.public else '_'
        with emit.block():
            emit_decl_items(emit, self.items)
            emit_decode_fn(emit, self.size == 'dyn', self.items, args=(f'{argname}: u8',))
            emit_deinit_fn(emit, self.size == 'dyn', self.items)
        emit('};')
        emit()
