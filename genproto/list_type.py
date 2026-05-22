from __future__ import annotations

from dataclasses import dataclass

from . import xcbxml
from .common import BaseType, Emit, Field, Resolver, Size, TypeProtocol, emit_expr


@dataclass(frozen=True)
class ListType(BaseType):
    item_type: TypeProtocol
    len: int | xcbxml.ListExpr | None

    @property
    def decl_name(self) -> str:
        if isinstance(self.len, int):
            return f'[{self.len}]{self.item_type.decl_name}'
        return f'[]const {self.item_type.decl_name}'

    @property
    def size(self) -> Size:
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
                emit(f'writer.write({value_expr});')
            else:
                emit(f'writer.write({value_expr}[0..]);')
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
                T.emit_decode(emit, 'elem.*')
            emit('}')
            return

        if '.' not in value_expr:
            raise NotImplementedError(f'dynamic list decode requires dotted target: {value_expr}')
        owner_expr, _, name = value_expr.rpartition('.')
        if name == '*':
            raise NotImplementedError('dynamic list decode requires a named field target')
        if self.len is None:
            if T.decl_name == 'u8':
                emit('var bytes: std.ArrayList(u8) = .empty;')
                emit('defer bytes.deinit(allocator);')
                emit('try reader.appendRemainingUnlimited(allocator, &bytes);')
                emit(f'const decoded_{name}_buf = try bytes.toOwnedSlice(allocator);')
            else:
                emit(f'var decoded_{name}_list: std.ArrayList({T.decl_name}) = .empty;')
                emit(f'defer decoded_{name}_list.deinit(allocator);')
                emit('while (true) {')
                with emit.block():
                    emit('_ = reader.peekByte() catch |err| switch (err) {')
                    with emit.block():
                        emit('error.EndOfStream => break,')
                        emit('else => |e| return e,')
                    emit('};')
                    emit(f'var elem: {T.decl_name} = undefined;')
                    T.emit_decode(emit, 'elem')
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
                emit(
                    f'const decoded_{name}_buf = try allocator.dupe(u8, try reader.take({len_expr}));'
                )
            else:
                emit(f'const decoded_{name}_buf = try allocator.alloc({T.decl_name}, {len_expr});')
                emit(f'for (decoded_{name}_buf) |*elem| {{')
                with emit.block():
                    T.emit_decode(emit, 'elem.*')
                emit('}')
        emit(f'{value_expr} = decoded_{name}_buf;')
        emit(f'{owner_expr}.decoded_{name}_buf = decoded_{name}_buf;')

    def update_fieldref(self, field: Field, fields_by_name: dict[str, Field]) -> None:
        if isinstance(self.len, xcbxml.FieldRef):
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
    def from_schema(list_field: xcbxml.ListField, resolver: Resolver) -> ListType:
        item_type = resolver.get(list_field.item_type)
        return ListType(
            item_type=item_type,
            len=list_field.len_expr,
        )
