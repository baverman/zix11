from typing import Sequence

from . import xcbxml
from .common import Field, Resolver


def get_byte_slot(items: Sequence[Field]) -> Field | None:
    if items:
        field_type = items[0].type
        if isinstance(field_type, (ScalarType, EnumType, PadType)) and field_type.size == 1:
            return items[0]
    return None


def item_from_schema(
    item: xcbxml.DataFields
    | xcbxml.SwitchField
    | xcbxml.CaseSwitchField
    | xcbxml.RequiredStartAlign,
    resolver: Resolver,
    owner_name: str,
) -> Field:
    if isinstance(item, xcbxml.Field):
        for enum_name in (item.enum, item.mask):
            if enum_name is None:
                continue
            enum_type = resolver.get(enum_name)
            if not isinstance(enum_type, EnumType):
                raise NotImplementedError(f'field references non-enum as enum/mask: {enum_name}')
            enum_type.bind_scalar_type(SCALAR_TYPES[item.type])
        return Field(
            name=item.name, type=resolver.get(item.enum) if item.enum else resolver.get(item.type)
        )
    if isinstance(item, xcbxml.Pad):
        if item.count is None:
            raise NotImplementedError('pad alignment is not supported yet')
        return Field(name='_pad_', type=PadType(byte_count=item.count), public=False)
    if isinstance(item, xcbxml.ListField):
        return Field(name=item.name, type=ListType.from_schema(item, resolver))
    if isinstance(item, xcbxml.SwitchField):
        return Field(name=item.name, type=BitcaseType.from_schema(item, resolver, owner_name))
    if isinstance(item, xcbxml.CaseSwitchField):
        return Field(name=item.name, type=CaseType.from_schema(item, resolver, owner_name))
    raise NotImplementedError(f'unsupported struct item: {type(item).__name__}')


def build_items(
    schema_items: Sequence[
        xcbxml.DataFields | xcbxml.SwitchField | xcbxml.CaseSwitchField | xcbxml.RequiredStartAlign
    ],
    resolver: Resolver,
    owner_name: str,
) -> tuple[Field, ...]:
    items: list[Field] = []
    fields_by_name: dict[str, Field] = {}
    for item in schema_items:
        resolved = item_from_schema(item, resolver, owner_name)
        items.append(resolved)
        fields_by_name[resolved.name] = resolved
    for it in items:
        it.type.update_fieldref(it, fields_by_name)
    for i, it in enumerate(items):
        if isinstance(it.type, ListType) and it.type.len is None and i != len(items) - 1:
            raise NotImplementedError('tail lists must be the final item')
    return tuple(items)


from .list_type import ListType  # noqa
from .simple import SCALAR_TYPES, EnumType, PadType, ScalarType  # noqa
from .switch import BitcaseType, CaseType  # noqa
