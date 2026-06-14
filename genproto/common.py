from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, Literal, Mapping, Protocol, TypeVar

from . import xcbxml

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
    if name.isidentifier() and name not in ZIG_OPERATORS:
        return name
    return f'@"{name}"'


ZIG_OPERATORS = frozenset({'and', 'or'})

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


@dataclass(frozen=True)
class DecodeScope:
    owner_expr: str
    local_names: frozenset[str] = frozenset()

    @staticmethod
    def empty() -> DecodeScope:
        return DecodeScope(owner_expr='')

    def get(self, name: str) -> str:
        if name in self.local_names:
            return zig_local_name(name)
        if not self.owner_expr:
            raise NotImplementedError(f'decode argument requires owner scope: {name}')
        return f'{self.owner_expr}.{name}'


class TypeProtocol(Protocol):
    @property
    def size(self) -> Size: ...

    @property
    def decl_name(self) -> str: ...

    def emit_decl(self, emit: Emit, name: str) -> None: ...

    def emit_encode(self, emit: Emit, value_expr: str) -> None: ...

    def emit_decode(self, emit: Emit, value_expr: str, scope: DecodeScope) -> None: ...

    def emit_deinit(self, emit: Emit, value_expr: str) -> None: ...

    def decode_args(self) -> Mapping[str, str]: ...

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

    def decode_args(self) -> Mapping[str, str]:
        result = {'reader': '*std.Io.Reader'}
        if self.size == 'dyn':
            result['allocator'] = 'std.mem.Allocator'
        return result

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
        return zig_local_name(expr.ref)
    if isinstance(expr, xcbxml.Op):
        if (
            expr.op == '&'
            and isinstance(expr.right, xcbxml.Unop)
            and expr.right.op == '~'
            and isinstance(expr.right.expr, int)
        ):
            left = emit_expr(expr.left, prefix, element_expr)
            return f'({left} & ~@as(@TypeOf({left}), {expr.right.expr}))'
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


def emit_decode_expr(
    expr: xcbxml.ListExpr,
    scope: DecodeScope,
    element_expr: str | None = None,
    element_prefix: str | None = None,
) -> str:
    if isinstance(expr, int):
        return str(expr)
    if isinstance(expr, xcbxml.FieldRef):
        if element_prefix is not None:
            return f'{element_prefix}.{expr.ref}'
        if '.' in expr.ref:
            return expr.ref
        return scope.get(expr.ref)
    if isinstance(expr, xcbxml.ParamRef):
        value = scope.get(expr.ref)
        return f'@intFromBool({value})' if expr.type == 'bool' else value
    if isinstance(expr, xcbxml.Op):
        if (
            expr.op == '&'
            and isinstance(expr.right, xcbxml.Unop)
            and expr.right.op == '~'
            and isinstance(expr.right.expr, int)
        ):
            left = emit_decode_expr(expr.left, scope, element_expr, element_prefix)
            return f'({left} & ~@as(@TypeOf({left}), {expr.right.expr}))'
        return f'({emit_decode_expr(expr.left, scope, element_expr, element_prefix)} {expr.op} {emit_decode_expr(expr.right, scope, element_expr, element_prefix)})'
    if isinstance(expr, xcbxml.Unop):
        return f'({expr.op}{emit_decode_expr(expr.expr, scope, element_expr, element_prefix)})'
    if isinstance(expr, xcbxml.PopCount):
        return f'@popCount({emit_decode_expr(expr.expr, scope, element_expr, element_prefix)})'
    if isinstance(expr, xcbxml.SumOf):
        elem_value = emit_decode_expr(expr.expr, scope, 'elem', 'elem')
        return (
            f'(blk: {{ var total: usize = 0; for ({scope.get(expr.ref)}) |elem| '
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

    def emit_decode(self, emit: Emit, value_expr: str, scope: DecodeScope) -> None:
        _ = scope
        emit(f'{value_expr} = {self.base_type.coerce_from_raw(self.arg_name)};')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        self.base_type.emit_deinit(emit, value_expr)

    def decode_args(self) -> Mapping[str, str]:
        return (
            {'header_': 'wire.ReplyHeader'}
            if self.arg_name.split('.', 1)[0] == 'header_'
            else self.base_type.decode_args()
        )


def emit_decl_items(emit: Emit, items: Iterable[Field]) -> None:
    for item in items:
        if item.public:
            item.type.emit_decl(emit, item.name)

    for item in items:
        if item.public and isinstance(item.type, InnerType):
            emit()
            item.type.emit_definition(emit)


def emit_encode_fn(emit: Emit, items: Iterable[Field]) -> None:
    emit('pub fn encode(self: *const @This(), writer: *std.Io.Writer) errors.EncodeError!void {')
    with emit.block():
        emitted = False
        for item in items:
            emitted = True
            item.type.emit_encode(emit, item.encode_value_expr('self'))
        if not emitted:
            emit('_ = self;')
            emit('_ = writer;')
    emit('}')


COMMON_ARGS = {
    'allocator': 'std.mem.Allocator',
    'buffer_': '[]u8',
    'reader': '*std.Io.Reader',
    'header_': 'wire.ReplyHeader',
}

COMMON_ARGS_ORDER = ['allocator', 'buffer_', 'reader', 'header_']


def collect_decode_args(items: Iterable[Field]) -> Mapping[str, str]:
    items = tuple(items)
    field_names = {item.name for item in items}
    args: dict[str, str] = {}
    for item in items:
        for name, ztype in item.type.decode_args().items():
            if name in field_names:
                continue
            args[name] = ztype
    return args


def ordered_decode_args(args: Mapping[str, str]) -> list[str]:
    result = []
    for arg in COMMON_ARGS_ORDER:
        if arg in args:
            result.append(arg)

    result.extend(sorted([it for it in args if it not in COMMON_ARGS]))
    return result


def decode_call_args(args: Mapping[str, str], scope: DecodeScope) -> list[str]:
    result: list[str] = []
    for name in ordered_decode_args(args):
        if name in COMMON_ARGS:
            result.append(name)
        else:
            result.append(scope.get(name))
    return result


def decode_error_set(args: Mapping[str, str]) -> str:
    if 'buffer_' in args:
        return 'errors.BufferDecodeError'
    if 'allocator' in args:
        return 'errors.AllocDecodeError'
    return 'errors.DecodeError'


def expr_decode_args(expr: xcbxml.ListExpr) -> dict[str, str]:
    if isinstance(expr, xcbxml.FieldRef):
        if expr.ref.split('.', 1)[0] == 'header_':
            return {'header_': 'wire.ReplyHeader'}
        return {}
    if isinstance(expr, xcbxml.ParamRef):
        return {expr.ref: expr.type}
    if isinstance(expr, xcbxml.Op):
        return {**expr_decode_args(expr.left), **expr_decode_args(expr.right)}
    if isinstance(expr, xcbxml.Unop):
        return expr_decode_args(expr.expr)
    if isinstance(expr, xcbxml.PopCount):
        return expr_decode_args(expr.expr)
    if isinstance(expr, xcbxml.SumOf):
        return expr_decode_args(expr.expr)
    return {}


def replace_field_ref_in_expr(
    expr: xcbxml.ListExpr,
    ref: str,
    replacement: xcbxml.ListExpr,
) -> xcbxml.ListExpr:
    if isinstance(expr, xcbxml.FieldRef) and expr.ref == ref:
        return replacement
    if isinstance(expr, xcbxml.PopCount):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, replacement)
    elif isinstance(expr, xcbxml.SumOf):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, replacement)
    elif isinstance(expr, xcbxml.Op):
        expr.left = replace_field_ref_in_expr(expr.left, ref, replacement)
        expr.right = replace_field_ref_in_expr(expr.right, ref, replacement)
    elif isinstance(expr, xcbxml.Unop):
        expr.expr = replace_field_ref_in_expr(expr.expr, ref, replacement)
    return expr


def emit_decode_fn(
    emit: Emit,
    items: Iterable[Field],
    mandatory_args: tuple[str, ...] = (),
) -> None:
    items = tuple(items)
    item_args = collect_decode_args(items)

    args = {**{arg: COMMON_ARGS[arg] for arg in mandatory_args}, **item_args}
    unused_args = args.keys() - item_args.keys()

    fargs: list[str] = [
        f'{zig_local_name(name)}: {COMMON_ARGS.get(name, args[name])}'
        for name in ordered_decode_args(args)
    ]
    local_names = frozenset([*args, *(item.name for item in items if not item.public)])
    scope = DecodeScope(owner_expr='result', local_names=local_names)

    emit(f'pub fn decode({", ".join(fargs)}) {decode_error_set(args)}!@This() {{')
    with emit.block():
        emit('var result: @This() = undefined;')
        for arg in unused_args:
            emit(f'_ = {arg};')
        for item in items:
            item.type.emit_decode(emit, item.decode_target_expr('result'), scope)
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
    if isinstance(expr, xcbxml.ParamRef):
        return []
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
