from __future__ import annotations
from typing import Callable, Generic, TypeVar, Iterable, Any, Union

import sys
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from functools import cached_property

T = TypeVar('T')
T_co = TypeVar('T_co', covariant=True)


class MatchError(Exception):
    def __init__(self, message: str, item: ET.Element) -> None:
        super().__init__(message, ET.tostring(item))


@dataclass
class Item(Generic[T]):
    tag: str
    attrs: set[str]
    kids: Seq | Many | AnyItem | StructItem | None = None
    cnv: None | Callable[[dict[str, object]], T] = None

    def match(self, node: ET.Element) -> T:
        if self.tag != node.tag:
            raise MatchError(f'Expected tag: {self.tag}', node)

        if not self.attrs.issuperset(node.attrib):
            raise MatchError(f'Expected attrs: {self.attrs}', node)

        # Fishy request, has ambigous xml desc
        if node.tag == 'request' and node.attrib['name'] == 'QueryTextExtents':
            return None  # type: ignore[return-value]

        attrs: dict[str, object] = dict(node.attrib)
        if self.kids is None:
            if list(node):
                raise MatchError('Expected no children', node)
        else:
            attrs['@kids'] = self.kids.match(node)

        if self.cnv:
            return self.cnv(attrs)
        else:
            return Node(node.tag, attrs)  # type: ignore[return-value]


@dataclass
class TextItem(Generic[T]):
    tag: str
    attrs: set[str] | frozenset[str] = frozenset()
    cnv: None | Callable[[dict[str, object], str], T] = None

    def match(self, node: ET.Element) -> object:
        if self.tag != node.tag:
            raise MatchError(f'Expected tag: {self.tag}', node)

        if not self.attrs.issuperset(node.attrib):
            raise MatchError(f'Expected attrs: {self.attrs}', node)

        if self.cnv:
            return self.cnv(node.attrib, node.text)  # type: ignore[arg-type]
        else:
            return TextNode(node.tag, node.attrib, node.text)  # type: ignore[arg-type]


@dataclass
class IgnoreItem:
    tag: str

    def match(self, node: ET.Element) -> object:
        if self.tag != node.tag:
            raise MatchError(f'Expected tag: {self.tag}', node)
        return None


class Ref(Generic[T_co]):
    def __init__(self, ref: str) -> None:
        self.locals = sys._getframe(2).f_locals
        self.ref = ref

    def obj(self) -> T_co:
        return self.locals[self.ref]  # type:ignore[no-any-return]


OnlyItem = Item[Any] | TextItem[Any] | IgnoreItem
AnyItem = Union[OnlyItem, 'OneOf']
AnyItemRef = AnyItem | Ref[AnyItem]


@dataclass
class OneOf:
    items: tuple[OnlyItem, ...]

    @cached_property
    def tags(self) -> dict[str, list[OnlyItem]]:
        result: dict[str, list[OnlyItem]] = {}
        for item in self.items:
            result.setdefault(item.tag, []).append(item)
        return result

    def match(self, node: ET.Element) -> object:
        if node.tag not in self.tags:
            raise MatchError(f'Expected one of tags: {list(self.tags)}', node)
        last_error: MatchError | None = None
        for item in self.tags[node.tag]:
            try:
                return item.match(node)
            except MatchError as err:
                last_error = err
        assert last_error is not None
        raise last_error


class Seq:
    def __init__(self, *items: AnyItemRef, optional: bool = False) -> None:
        self._items = items
        self.optional = optional

    @cached_property
    def items(self) -> list[AnyItem]:
        return [resolve_ref(it) for it in self._items]  # type: ignore[misc]

    def match(self, node: ET.Element | Iterable[ET.Element]) -> list[object]:
        kids = list(node)
        if not kids and self.optional:
            return []

        if len(self.items) != len(kids):
            raise MatchError('Expected children amount: {len(self.items)}', node)  # type: ignore[arg-type]

        return [m.match(it) for it, m in zip(kids, self.items)]


class Many:
    def __init__(self, matcher: AnyItemRef):
        self._matcher = matcher

    @cached_property
    def matcher(self) -> AnyItem:
        return resolve_ref(self._matcher)  #type: ignore[return-value]

    def match(self, node: ET.Element | Iterable[ET.Element]) -> list[object]:
        result = []
        m = self.matcher
        for it in node:
            v = m.match(it)
            if v is not None:
                result.append(v)
        return result


class Opt:
    def __init__(self, matcher: OnlyItem) -> None:
        self.matcher = matcher


class StructItem:
    def __init__(self, **kwargs: OnlyItem | Many | Seq | Opt):
        self.matchers = kwargs

    def match(self, node: ET.Element) -> dict[str, object | list[object]]:
        mlen = 0
        dkids: dict[str, list[ET.Element]] = {}
        for it in node:
            if it.tag in self.matchers:
                key = it.tag
            else:
                key = '_'
            dkids.setdefault(key, []).append(it)

        result = {}
        for k, m in self.matchers.items():
            kids = dkids.get(k, [])
            mlen += len(kids)

            v: object | list[object]
            if isinstance(m, (Many, Seq)):
                v = m.match(kids)
            elif isinstance(m, Opt):
                if not kids:
                    v = None
                elif len(kids) > 1:
                    raise MatchError(f'{k} expects only single child', node)
                else:
                    v = m.matcher.match(kids[0])
            else:
                if len(kids) != 1:
                    raise MatchError(f'{k} expects only single child', node)
                v = m.match(kids[0])

            result[k] = v

        if mlen != len(node):
            raise MatchError(f'Expected one of tags: {list(self.matchers)}', node)

        return result


def one_of(*items: OnlyItem) -> OneOf:
    return OneOf(items)


@dataclass
class Node:
    tag: str
    attrs: dict[str, object]


@dataclass
class TextNode:
    tag: str
    attrs: dict[str, object]
    value: str


def resolve_ref(obj_or_ref: T | Ref[T]) -> T:
    if isinstance(obj_or_ref, Ref):
        return obj_or_ref.obj()
    else:
        return obj_or_ref
