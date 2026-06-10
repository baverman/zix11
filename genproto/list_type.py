from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, cast

from . import xcbxml
from .common import BaseType, Emit, Field, Parent, Size, TypeProtocol, emit_expr
from .resolver import Resolver

if TYPE_CHECKING:
    from .struct import StructType


@dataclass
class ListType(BaseType):
    item_type: TypeProtocol
    len: int | xcbxml.ListExpr | None
    use_buffer: bool = False

    @property
    def decl_name(self) -> str:
        if isinstance(self.len, int):
            return f'[{self.len}]{self.item_type.decl_name}'
        return f'[]const {self.item_type.decl_name}'

    @property
    def size(self) -> Size:
        if self.use_buffer:
            return 'fixed'
        if isinstance(self.len, int):
            if isinstance(self.item_type.size, int):
                return self.len * self.item_type.size
            return 'fixed'
        return 'dyn'

    def emit_decl(self, emit: Emit, name: str) -> None:
        emit(f'{name}: {self.decl_name},')
        if self.size == 'dyn':
            emit(f'decoded_{name}_buf: ?[]{self.item_type.decl_name} = null,')

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        if self.item_type.decl_name == 'u8':
            if self.size == 'dyn':
                emit(f'try writer.writeAll({value_expr});')
            else:
                emit(f'try writer.writeAll({value_expr}[0..]);')
        else:
            emit(f'for ({value_expr}) |elem| {{')
            with emit.block():
                self.item_type.emit_encode(emit, 'elem')
            emit('}')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        T = self.item_type
        if isinstance(self.len, int):
            emit(f'for (&{value_expr}) |*elem| {{')
            with emit.block():
                self.emit_element_decode(emit, 'elem.*', value_expr.rpartition('.')[0])
            emit('}')
            return

        if '.' not in value_expr:
            raise NotImplementedError(f'dynamic list decode requires dotted target: {value_expr}')

        owner_expr, _, name = value_expr.rpartition('.')
        if name == '*':
            raise NotImplementedError('dynamic list decode requires a named field target')

        if self.len is None:
            if T.decl_name == 'u8':
                if self.use_buffer:
                    raise NotImplementedError('implicit length for buffered decode is unsupported')
                else:
                    emit('var bytes: std.ArrayList(u8) = .empty;')
                    emit('defer bytes.deinit(allocator);')
                    emit('try reader.appendRemainingUnlimited(allocator, &bytes);')
                    emit(f'const decoded_{name}_buf = try bytes.toOwnedSlice(allocator);')
            else:
                emit(f'var decoded_{name}_list: std.ArrayList({T.decl_name}) = .empty;')
                emit(f'defer decoded_{name}_list.deinit(allocator);')
                emit('while (true) {')
                # TODO: use reader facility to detect end before read not errors
                with emit.block():
                    emit('_ = reader.peekByte() catch |err| switch (err) {')
                    with emit.block():
                        emit('error.EndOfStream => break,')
                        emit('else => |e| return e,')
                    emit('};')
                    emit(f'var elem: {T.decl_name} = undefined;')
                    self.emit_element_decode(emit, 'elem', owner_expr)
                    emit(f'try decoded_{name}_list.append(allocator, elem);')
                emit('}')
                emit(f'const decoded_{name}_buf = try decoded_{name}_list.toOwnedSlice(allocator);')
        else:
            if isinstance(self.len, xcbxml.FieldRef):
                len_expr = emit_expr(self.len, '')
            else:
                len_expr = emit_expr(self.len, f'{owner_expr}.')
            len_expr = f'@intCast({len_expr})'
            if T.decl_name == 'u8':
                if self.use_buffer:
                    emit(f'const {name}_len: usize = {len_expr};')
                    emit(f'if (buffer_.len < {name}_len) return error.BufferTooSmall;')
                    emit(f'@memcpy(buffer_[0..{name}_len], try reader.take({name}_len));')
                    emit(f'const decoded_{name}_buf = buffer_[0..{name}_len];')
                else:
                    emit(
                        f'const decoded_{name}_buf = try allocator.dupe(u8, try reader.take({len_expr}));'
                    )
            else:
                emit(f'const decoded_{name}_buf = try allocator.alloc({T.decl_name}, {len_expr});')
                emit(f'for (decoded_{name}_buf) |*elem| {{')
                with emit.block():
                    self.emit_element_decode(emit, 'elem.*', owner_expr)
                emit('}')

        emit(f'{value_expr} = decoded_{name}_buf;')
        if not self.use_buffer:
            emit(f'{owner_expr}.decoded_{name}_buf = decoded_{name}_buf;')

    # TODO: oh well, it's quite an ugly hack, I don't see why it have to use getattr
    def emit_element_decode(self, emit: Emit, target: str, owner_expr: str) -> None:
        params = getattr(self.item_type, 'decode_params', ())
        if params:
            args = ''.join(f', {owner_expr}.{name}' for name, _ in params)
            cast('StructType', self.item_type).emit_decode(emit, target, decode_args=args)
        else:
            self.item_type.emit_decode(emit, target)

    def decode_args(self) -> Mapping[str, str]:
        args = dict(super().decode_args())
        if isinstance(self.len, xcbxml.FieldRef) and self.len.ref.split('.', 1)[0] == 'header_':
            args['header_'] = 'wire.ReplyHeader'
        if self.use_buffer:
            args['buffer_'] = '[]u8'
        return args

    def free_decode_args(self, resolver: Resolver) -> list[tuple[str, str]]:
        if isinstance(self.len, xcbxml.ParamRef):
            return [(self.len.ref, resolver.get(self.len.type).decl_name)]
        return []

    def update_fieldref(
        self, parents: tuple[Parent, ...], field: Field, fields_by_name: dict[str, Field]
    ) -> None:
        if isinstance(self.len, xcbxml.FieldRef):
            if (
                self.len.ref == 'length'
                and self.len.ref not in fields_by_name
                and isinstance(parents[-1], xcbxml.Reply)
            ):
                self.len = xcbxml.FieldRef('header_.length')
                return

            if self.len.ref in fields_by_name:
                len_field = fields_by_name[self.len.ref]
                len_field.public = False
                len_field.encode_value_expr_ = f'@intCast({{owner}}.{field.name}.len)'

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        T = self.item_type
        if self.size == 'dyn':
            if '.' not in value_expr:
                raise NotImplementedError(
                    f'dynamic list deinit requires dotted target: {value_expr}'
                )
            owner_expr, name = value_expr.rsplit('.', 1)
            if name == '*':
                raise NotImplementedError('dynamic list deinit requires a named field target')
            emit(f'if ({owner_expr}.decoded_{name}_buf) |buf| {{')
            with emit.block():
                if T.size == 'dyn':
                    emit('for (buf) |*it| {')
                    with emit.block():
                        T.emit_deinit(emit, 'it')
                    emit('}')
                emit('allocator.free(buf);')
                emit(f'{owner_expr}.decoded_{name}_buf = null;')
                emit(f'{owner_expr}.{name} = &.{{}};')
            emit('}')
        elif T.size == 'dyn':
            emit(f'for ({value_expr}) |*it| {{')
            with emit.block():
                T.emit_deinit(emit, 'it')
            emit('}')

    @staticmethod
    def from_schema(
        list_field: xcbxml.ListField,
        resolver: Resolver,
    ) -> ListType:
        item_type = resolver.get(list_field.item_type)
        len_expr = list_field.len_expr
        return ListType(item_type=item_type, len=len_expr)
