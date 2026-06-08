from typing import Sequence

from . import xcbxml
from .common import Field, Parent
from .resolver import Resolver


def collect_decode_params(
    items: Sequence[Field], resolver: Resolver
) -> tuple[tuple[str, str], ...]:
    field_names = {it.name for it in items}
    seen: set[str] = set()
    params: list[tuple[str, str]] = []
    for it in items:
        for name, ztype in it.type.free_decode_args(resolver):
            if name in field_names or name in seen:
                continue
            seen.add(name)
            params.append((name, ztype))
    return tuple(params)


def get_byte_slot(items: Sequence[Field]) -> Field | None:
    if items:
        field_type = items[0].type
        if isinstance(field_type, (ScalarType, EnumWireType, PadType)) and field_type.size == 1:
            return items[0]
    return None


def item_from_schema(
    parents: tuple[Parent, ...],
    item: xcbxml.DataFields
    | xcbxml.SwitchField
    | xcbxml.CaseSwitchField
    | xcbxml.RequiredStartAlign,
    resolver: Resolver,
    owner_name: str,
) -> Field:
    if isinstance(item, xcbxml.Field):
        if item.enum is not None:
            enum_type = resolver.get(item.enum)
            if not isinstance(enum_type, EnumType):
                raise NotImplementedError(f'field references non-enum as enum: {item.enum}')
            wire_type = resolver.get(item.type)
            if not isinstance(wire_type, ScalarType):
                raise NotImplementedError(f'enum field must use scalar wire type: {item.type}')
            if wire_type.name == 'bool':
                wire_type = SCALAR_TYPES['CARD8']
            return Field(
                name=item.name,
                type=EnumWireType(enum_type=enum_type, scalar_type=wire_type),
            )
        if item.mask is not None:
            enum_type = resolver.get(item.mask)
            if not isinstance(enum_type, EnumType):
                raise NotImplementedError(f'field references non-enum as mask: {item.mask}')
            enum_type.is_mask = True
            return Field(name=item.name, type=resolver.get(item.type))
        return Field(name=item.name, type=resolver.get(item.type))
    if isinstance(item, xcbxml.Pad):
        if item.count is None:
            assert item.align is not None
            return Field(name='_pad_', type=AlignPadType(alignment=item.align), public=False)
        return Field(name='_pad_', type=PadType(byte_count=item.count), public=False)
    if isinstance(item, xcbxml.RequiredStartAlign):
        return Field(
            name='_pad_',
            type=RequiredStartAlignType(alignment=item.align, offset=item.offset),
            public=False,
        )
    if isinstance(item, xcbxml.ListField):
        return Field(
            name=item.name,
            type=ListType.from_schema(item, resolver),
        )
    if isinstance(item, xcbxml.SwitchField):
        return Field(
            name=item.name, type=BitcaseType.from_schema(item, resolver, parents, owner_name)
        )
    if isinstance(item, xcbxml.CaseSwitchField):
        return Field(name=item.name, type=CaseType.from_schema(item, resolver, parents, owner_name))
    raise NotImplementedError(f'unsupported struct item: {type(item).__name__}')


def build_items(
    parents: tuple[Parent, ...],
    schema_items: Sequence[
        xcbxml.DataFields | xcbxml.SwitchField | xcbxml.CaseSwitchField | xcbxml.RequiredStartAlign
    ],
    resolver: Resolver,
    owner_name: str,
) -> list[Field]:
    items: list[Field] = []
    fields_by_name: dict[str, Field] = {}

    for item in schema_items:
        resolved = item_from_schema(
            parents,
            item,
            resolver,
            owner_name,
        )
        items.append(resolved)
        fields_by_name[resolved.name] = resolved

    for it in items:
        it.type.update_fieldref(parents, it, fields_by_name)

    for i, it in enumerate(items):
        if isinstance(it.type, ListType) and it.type.len is None and i != len(items) - 1:
            raise NotImplementedError('tail lists must be the final item')
    return items


from .list_type import ListType  # noqa
from .simple import (  # noqa
    SCALAR_TYPES,
    AlignPadType,
    EnumType,
    EnumWireType,
    PadType,
    RequiredStartAlignType,
    ScalarType,
)
from .switch import BitcaseType, CaseType  # noqa
