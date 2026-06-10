from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import xcbxml
from .common import (
    BaseType,
    DecodeScope,
    Emit,
    Field,
    InjectedType,
    Size,
    emit_decl_items,
    emit_decode_fn,
    emit_deinit_fn,
    emit_encode_fn,
    items_size,
)
from .fields import build_items, get_byte_slot
from .list_type import ListType
from .resolver import Resolver

REPLY_BYTE_EXPR = 'header_.byte_slot'
USE_BUFFER_REPLY = ('GetProperty',)


@dataclass(frozen=True)
class RequestType:
    name: str
    opcode: int
    is_core: bool
    byte_slot: Field | None
    items: list[Field]
    reply: ReplyType | None

    @staticmethod
    def from_schema(request: xcbxml.Request, resolver: Resolver, is_core: bool) -> RequestType:
        items = build_items((request,), request.fields, resolver, request.name)

        return RequestType(
            name=request.name,
            opcode=int(request.opcode),
            is_core=is_core,
            byte_slot=get_byte_slot(items) if is_core else None,
            items=items,
            reply=None
            if request.reply is None
            else ReplyType.from_schema(
                request.name,
                request.reply,
                resolver,
                is_core=is_core,
                use_buffer=request.name in USE_BUFFER_REPLY,
            ),
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
            emit('pub const extension = current_mod.extension;')
            emit()

            emit_decl_items(emit, self.items)
            emit()

            if self.is_core:
                self.emit_header_byte1(emit)
                emit()

            emit_encode_fn(emit, encode_items)
            emit()

            if self.reply:
                self.reply.emit_definition(emit)
            else:
                emit('pub const Reply = void;')

        emit('};')


@dataclass(frozen=True)
class ReplyType(BaseType):
    byte_slot: Field | None
    items: list[Field]
    use_buffer: bool

    @staticmethod
    def from_schema(
        request_name: str,
        reply: xcbxml.Reply,
        resolver: Resolver,
        is_core: bool,
        use_buffer: bool,
    ) -> ReplyType:
        items = build_items((reply,), reply.fields, resolver, f'{request_name}Reply')

        if use_buffer:
            assert isinstance(items[-1].type, ListType)
            items[-1].type.use_buffer = True

        byte_slot = get_byte_slot(items)
        if byte_slot:
            if byte_slot.name != '_pad_':
                items = [
                    Field(
                        name=byte_slot.name,
                        type=InjectedType(arg_name=REPLY_BYTE_EXPR, base_type=byte_slot.type),
                        public=byte_slot.public,
                    ),
                    *items[1:],
                ]
            else:
                items = items[1:]

        return ReplyType(byte_slot=byte_slot, items=items, use_buffer=use_buffer)

    @property
    def decl_name(self) -> str:
        return 'Reply'

    @cached_property
    def size(self) -> Size:
        return items_size(self.items)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_decode(self, emit: Emit, var_decl: str, scope: DecodeScope) -> None:
        _ = emit
        _ = var_decl
        _ = scope
        raise NotImplementedError

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_definition(self, emit: Emit) -> None:
        emit('pub const Reply = struct {')
        with emit.block():
            emit_decl_items(emit, self.items)
            emit()

            emit_decode_fn(
                emit,
                self.items,
                mandatory_args=('reader', 'header_'),
            )

            if self.size == 'dyn':
                emit()
                emit_deinit_fn(emit, self.items)
        emit('};')
