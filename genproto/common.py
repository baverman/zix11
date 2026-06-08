from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator, Literal, Protocol, Sequence, TypeVar

from . import xcbxml

if TYPE_CHECKING:
    from .resolver import Resolver

Size = int | Literal['dyn'] | Literal['fixed']
Parent = (
    xcbxml.Request
    | xcbxml.Reply
    | xcbxml.Union
    | xcbxml.Struct
    | xcbxml.Event
    | xcbxml.SwitchField
    | xcbxml.CaseSwitchField
)


def zig_tag_name(name: str) -> str:
    if name.isidentifier() and not name[0].isdigit():
        return name
    return f'@"{name}"'


ZIG_RESERVED = frozenset(
    {
        'type',
        'and',
        'or',
    }
)


def zig_local_name(name: str) -> str:
    if not name.isidentifier() or name[0].isdigit() or name in ZIG_RESERVED:
        return f'@"{name}"'
    return name


class Emit:
    def __init__(self) -> None:
        self.indent = 0
        self.lines: list[str] = []

    def __call__(self, text: str = '') -> None:
        if text:
            self.lines.append(('    ' * self.indent) + text)
        else:
            self.lines.append('')

    @contextmanager
    def block(self) -> Iterator[None]:
        self.indent += 1
        try:
            yield
        finally:
            self.indent -= 1

    def render(self) -> str:
        return '\n'.join(self.lines)


class TypeProtocol(Protocol):
    @property
    def size(self) -> Size: ...

    @property
    def decl_name(self) -> str: ...

    def emit_decl(self, emit: Emit, name: str) -> None: ...

    def emit_encode(self, emit: Emit, value_expr: str) -> None: ...

    def emit_decode(self, emit: Emit, value_expr: str) -> None: ...

    def emit_deinit(self, emit: Emit, value_expr: str) -> None: ...

    def decode_args(self) -> set[str]: ...

    def free_decode_args(self, resolver: Resolver) -> list[tuple[str, str]]: ...

    def update_fieldref(
        self, parents: tuple[Parent, ...], field: Field, fields_by_name: dict[str, Field]
    ) -> None: ...

    def coerce_to_raw(self, value_expr: str) -> str: ...

    def coerce_from_raw(self, value_expr: str) -> str: ...

    def with_module_prefix(self: TypeProtocolT, prefix: str) -> TypeProtocolT: ...


TypeProtocolT = TypeVar('TypeProtocolT', bound=TypeProtocol)


class BaseType(TypeProtocol):
    def with_module_prefix(self: TypeProtocolT, prefix: str) -> TypeProtocolT:
        _ = prefix
        return self

    def decode_args(self) -> set[str]:
        return {'reader'}

    def free_decode_args(self, resolver: Resolver) -> list[tuple[str, str]]:
        return []

    def coerce_from_raw(self, value_expr: str) -> str:
        return value_expr

    def coerce_to_raw(self, value_expr: str) -> str:
        return value_expr

    def update_fieldref(
        self, parents: tuple[Parent, ...], field: Field, fields_by_name: dict[str, Field]
    ) -> None:
        _ = parents
        _ = field
        _ = fields_by_name

    def emit_decl(self, emit: Emit, name: str) -> None:
        emit(f'{name}: {self.decl_name},')


class InnerType(BaseType):
    def emit_definition(self, emit: Emit) -> None:
        pass


@dataclass
class Field:
    name: str
    type: TypeProtocol
    public: bool = True
    encode_value_expr_: str | None = None

    def encode_value_expr(self, owner_expr: str) -> str:
        if self.encode_value_expr_ is not None:
            return self.encode_value_expr_.format(owner=owner_expr)
        return f'{owner_expr}.{self.name}'

    def decode_target_expr(self, owner_expr: str) -> str:
        if self.public:
            return f'{owner_expr}.{self.name}'
        return f'const {zig_local_name(self.name)}'


def emit_expr(expr: xcbxml.ListExpr, prefix: str, element_expr: str | None = None) -> str:
    if isinstance(expr, int):
        return str(expr)
    if isinstance(expr, xcbxml.FieldRef):
        return f'{prefix}{expr.ref}'
    if isinstance(expr, xcbxml.ParamRef):
        return expr.ref
    if isinstance(expr, xcbxml.Op):
        return f'({emit_expr(expr.left, prefix, element_expr)} {expr.op} {emit_expr(expr.right, prefix, element_expr)})'
    if isinstance(expr, xcbxml.Unop):
        return f'({expr.op}{emit_expr(expr.expr, prefix, element_expr)})'
    if isinstance(expr, xcbxml.PopCount):
        return f'@popCount({emit_expr(expr.expr, prefix, element_expr)})'
    if isinstance(expr, xcbxml.SumOf):
        elem_value = emit_expr(expr.expr, 'elem.', 'elem')
        return (
            f'(blk: {{ var total: usize = 0; for ({prefix}{expr.ref}) |elem| '
            f'total += @as(usize, {elem_value}); break :blk total; }})'
        )
    if isinstance(expr, xcbxml.ListElementRef):
        if element_expr is None:
            raise NotImplementedError('listelement-ref requires list element context')
        return element_expr
    raise NotImplementedError(f'unsupported list expression: {type(expr).__name__}')


@dataclass(frozen=True)
class InjectedType(BaseType):
    arg_name: str
    base_type: TypeProtocol

    @property
    def size(self) -> Size:
        return self.base_type.size

    @property
    def decl_name(self) -> str:
        return self.base_type.decl_name

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        self.base_type.emit_encode(emit, value_expr)

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        emit(f'{value_expr} = {self.base_type.coerce_from_raw(self.arg_name)};')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        self.base_type.emit_deinit(emit, value_expr)

    def decode_args(self) -> set[str]:
        return {'header_'} if self.arg_name.split('.', 1)[0] == 'header_' else set()


def emit_decl_items(emit: Emit, items: Iterable[Field]) -> None:
    for item in items:
        if item.public:
            item.type.emit_decl(emit, item.name)

    for item in items:
        if item.public and isinstance(item.type, InnerType):
            emit()
            item.type.emit_definition(emit)


def emit_encode_fn(emit: Emit, items: Iterable[Field]) -> None:
    emit('pub fn encode(self: *const @This(), writer: anytype) !void {')
    with emit.block():
        emitted = False
        for item in items:
            emitted = True
            item.type.emit_encode(emit, item.encode_value_expr('self'))
        if not emitted:
            emit('_ = self;')
            emit('_ = writer;')
    emit('}')


def emit_decode_fn(
    emit: Emit,
    is_dynamic: bool,
    items: Iterable[Field],
    args: Sequence[str] | None = None,
    unused_args: tuple[str, ...] = (),
) -> None:
    fargs = []
    if is_dynamic:
        fargs.append('allocator: std.mem.Allocator')
    fargs.append('reader: *std.Io.Reader')
    fargs.extend(args or ())

    emit(f'pub fn decode({", ".join(fargs)}) !@This() {{')
    with emit.block():
        emit('var result: @This() = undefined;')
        for arg in unused_args:
            emit(f'_ = {arg};')
        for item in items:
            item.type.emit_decode(emit, item.decode_target_expr('result'))
        emit('return result;')
    emit('}')


def emit_deinit_fn(emit: Emit, items: Iterable[Field]) -> None:
    emit('pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {')
    with emit.block():
        emit_deinit_items(emit, items)
    emit('}')


def emit_deinit_items(emit: Emit, items: Iterable[Field]) -> None:
    for item in items:
        item.type.emit_deinit(emit, f'self.{item.name}')


def expr_refs(expr: xcbxml.ListExpr) -> list[str]:
    if isinstance(expr, int):
        return []
    if isinstance(expr, xcbxml.FieldRef):
        return [expr.ref]
    if isinstance(expr, xcbxml.Op):
        return expr_refs(expr.left) + expr_refs(expr.right)
    if isinstance(expr, xcbxml.Unop):
        return expr_refs(expr.expr)
    if isinstance(expr, xcbxml.PopCount):
        return expr_refs(expr.expr)
    if isinstance(expr, xcbxml.SumOf):
        return [expr.ref] + expr_refs(expr.expr)
    if isinstance(expr, xcbxml.ListElementRef):
        return []
    raise NotImplementedError(f'unsupported list expression: {type(expr).__name__}')


def items_size(items: Iterable[Field]) -> Size:
    size = 0
    unknown = False
    for it in items:
        sz = it.type.size
        if sz == 'dyn':
            return 'dyn'
        elif sz == 'fixed':
            unknown = True
        else:
            size += sz

    if unknown:
        return 'fixed'

    return size
