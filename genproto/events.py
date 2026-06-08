from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Sequence

from . import xcbxml
from .common import (
    BaseType,
    Emit,
    Field,
    Size,
    emit_decl_items,
    emit_deinit_items,
    expr_refs,
    items_size,
)
from .fields import build_items, get_byte_slot
from .list_type import ListType
from .resolver import Resolver

if TYPE_CHECKING:
    from . import Module


@dataclass(frozen=True)
class EventStructType(BaseType):
    name: str

    @property
    def decl_name(self) -> str:
        return self.name

    @property
    def size(self) -> Size:
        return 32

    @staticmethod
    def from_schema(eventstruct: xcbxml.EventStruct) -> EventStructType:
        return EventStructType(name=eventstruct.name)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        emit(f'writer.write({value_expr}.raw[0..]);')

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        emit(f'{value_expr} = try {self.name}.decode(reader);')

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def emit_definition(self, emit: Emit) -> None:
        emit(f'pub const {self.name} = struct {{')
        with emit.block():
            emit('raw: [32]u8,')
            emit()

            emit('pub fn fromRaw(raw: [32]u8) @This() {')
            with emit.block():
                emit('return .{ .raw = raw };')
            emit('}')
            emit()

            emit('pub fn asRaw(self: @This()) [32]u8 {')
            with emit.block():
                emit('return self.raw;')
            emit('}')
            emit()

            emit('pub fn encode(self: @This(), writer: anytype) void {')
            with emit.block():
                emit('writer.write(self.raw[0..]);')
            emit('}')
            emit()

            emit('pub fn decode(reader: *std.Io.Reader) !@This() {')
            with emit.block():
                emit('var raw: [32]u8 = undefined;')
                emit('@memcpy(raw[0..], try reader.take(32));')
                emit('return .{ .raw = raw };')
            emit('}')
        emit('};')


@dataclass(frozen=True)
class EventType(BaseType):
    name: str
    number: int
    xge: bool
    no_sequence_number: bool
    items: list[Field]
    orig: EventType | None = None
    module_prefix: str = ''

    @property
    def decl_name(self) -> str:
        return f'{self.module_prefix}{self.name}Event'

    @property
    def size(self) -> Size:
        return 'fixed'

    def with_module_prefix(self, prefix: str) -> EventType:
        return replace(self, module_prefix=prefix)

    def emit_encode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_decode(self, emit: Emit, value_expr: str) -> None:
        raise NotImplementedError

    def emit_deinit(self, emit: Emit, value_expr: str) -> None:
        _ = emit
        _ = value_expr

    def split_items(self) -> tuple[list[Field], list[Field]]:
        for i, item in enumerate(self.items):
            if item.type.size == 'dyn':
                return self.items[:i], self.items[i:]
        return self.items, []

    @staticmethod
    def from_schema(event: xcbxml.Event, resolver: Resolver) -> EventType:
        items = build_items((event,), event.fields, resolver, event.name)
        if items_size(items) == 'dyn' and event.xge != 'true':
            raise NotImplementedError('dynamic non-xge events are not supported')
        return EventType(
            name=f'{event.name}',
            number=int(event.number),
            xge=event.xge == 'true',
            no_sequence_number=event.no_sequence_number == 'true',
            items=items,
        )

    def copy_as(self, copy: xcbxml.EventCopy) -> EventType:
        orig = self.orig or self
        return replace(self, name=copy.name, number=int(copy.number), orig=orig)

    def emit_definition(self, emit: Emit) -> None:
        prefix_items, body_items = self.split_items()
        body_refs = set(self.body_prefix_refs(prefix_items, body_items))
        for item in prefix_items:
            if item.name in body_refs:
                item.public = True

        emit(f'pub const {self.name}Event = struct {{')
        with emit.block():
            if self.xge:
                emit('extension: u8,')
                emit('length: u32,')
                emit('event_type: u16,')

            emit_decl_items(emit, prefix_items)

            if body_items:
                emit('_body: []const u8,')
                emit()

                emit('pub const Body = struct {')
                with emit.block():
                    emit_decl_items(emit, body_items)
                    emit()
                    emit('pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {')
                    with emit.block():
                        emit_deinit_items(emit, body_items)
                    emit('}')
                emit('};')
                emit()

                emit('pub fn getBody(self: @This(), allocator: std.mem.Allocator) !Body {')
                with emit.block():
                    emit('var reader_impl: std.Io.Reader = .fixed(self._body);')
                    emit('const reader = &reader_impl;')
                    for name in self.body_prefix_refs(prefix_items, body_items):
                        emit(f'const {name} = self.{name};')
                    emit('var result: Body = undefined;')
                    for item in body_items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                    emit('return result;')
                emit('}')

            emit()
            emit('pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {')
            with emit.block():
                emit('var result: @This() = undefined;')
                if self.no_sequence_number:
                    for item in self.items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                elif self.xge:
                    if body_items:
                        emit('const header = try reader.peek(8);')
                        emit(
                            'const packet = try reader.peek(32 + @as(usize, std.mem.readInt(u32, header[4..8], .native)) * 4);'
                        )
                    emit('_ = try reader.takeByte();')
                    emit('result.extension = try reader.takeByte();')
                    emit('_ = try reader.takeInt(u16, .native);')
                    emit('result.length = try reader.takeInt(u32, .native);')
                    emit('result.event_type = try reader.takeInt(u16, .native);')
                    if not body_items:
                        emit('const payload_start_seek = reader.seek;')
                    for item in prefix_items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                    if body_items:
                        emit('result._body = packet[reader.seek..];')
                        emit('const remaining_packet_len = packet.len - reader.seek;')
                        emit(
                            'if (remaining_packet_len != 0) _ = try reader.take(remaining_packet_len);'
                        )
                    else:
                        emit('const xge_body_len = reader.seek - payload_start_seek;')
                        emit('const total_body_len = 22 + @as(usize, result.length) * 4;')
                        emit(
                            'if (xge_body_len < total_body_len) _ = try reader.take(total_body_len - xge_body_len);'
                        )
                else:
                    emit('_ = try reader.takeByte();')
                    if self.items:
                        header_item = get_byte_slot(self.items)
                        if header_item is not None:
                            header_item.type.emit_decode(
                                emit, header_item.decode_target_expr('result')
                            )
                            body_items = self.items[1:]
                        else:
                            emit('_ = try reader.takeByte();')
                            body_items = self.items
                    else:
                        emit('_ = try reader.takeByte();')
                        body_items = []
                    emit('_ = try reader.takeInt(u16, .native);')
                    for item in body_items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                emit('return result;')
            emit('}')
            if not self.xge:
                emit()
                self.emit_to_bytes(emit)
        emit('};')
        emit()

    def emit_to_bytes(self, emit: Emit) -> None:
        emit('pub fn toBytes(self: @This()) [32]u8 {')
        with emit.block():
            emit('var packet: [32]u8 = std.mem.zeroes([32]u8);')
            emit('var writer_impl = io.FixedBufferWriter.init(&packet);')
            emit('const writer = &writer_impl;')
            # Client is expected to rebase event code to actual first_event number
            emit(f'writer.writeByte({self.number});')
            if self.no_sequence_number:
                for item in self.items:
                    item.type.emit_encode(emit, item.encode_value_expr('self'))
            else:
                byte_slot = get_byte_slot(self.items)
                if byte_slot is not None:
                    byte_slot.type.emit_encode(emit, byte_slot.encode_value_expr('self'))
                    encode_items = self.items[1:]
                else:
                    emit('writer.writeByte(0);')
                    encode_items = self.items
                emit('writer.writeInt(u16, 0);')
                for item in encode_items:
                    item.type.emit_encode(emit, item.encode_value_expr('self'))
            emit('return packet;')
        emit('}')

    def body_prefix_refs(
        self,
        prefix_items: Sequence[Field],
        body_items: Sequence[Field],
    ) -> tuple[str, ...]:
        prefix_names = {item.name for item in prefix_items}
        result: list[str] = []
        seen: set[str] = set()
        for item in body_items:
            if isinstance(item.type, ListType) and item.type.len is not None:
                for name in expr_refs(item.type.len):
                    if name in prefix_names and name not in seen:
                        result.append(name)
                        seen.add(name)
        return tuple(result)


def resolve_types(module: Module) -> None:
    if any(ev.xge for ev in module.events.values()):
        module.resolver.get('GeGenericEvent')


def emit_definitions(emit: Emit, module: Module, events: Sequence[EventType]) -> None:
    for ev in events:
        if not ev.orig:
            ev.emit_definition(emit)

    normal_events = [it for it in events if not it.xge]
    xge_events = [it for it in events if it.xge]
    prefix = module.global_tagged_prefix()

    if normal_events:
        emit('pub fn decodeEvent(reader: *std.Io.Reader) DecodeError!global_events.Event {')
        with emit.block():
            emit('const code = (try reader.peek(1))[0] & 0x7f;')
            emit('return switch (code) {')
            with emit.block():
                for ev in normal_events:
                    orig = ev.orig or ev
                    emit(
                        f'{int(ev.number)} => .{{ .{prefix}{ev.name} = try {orig.name}Event.decode(reader) }},'
                    )
                # TODO: replace with wire implementation
                emit('else => blk: {')
                with emit.block():
                    emit('const packet = try reader.take(32);')
                    emit('var raw: [32]u8 = undefined;')
                    emit('@memcpy(raw[0..], packet);')
                    emit('break :blk .{ .Unknown = .{')
                    with emit.block():
                        emit('.code = packet[0] & 0x7f,')
                        emit('.sequence = std.mem.readInt(u16, packet[2..4], .native),')
                        emit('.raw = raw,')
                    emit('} };')
                emit('},')
            emit('};')
        emit('}')
        emit()

    if xge_events:
        emit('pub fn decodeXgeEvent(reader: *std.Io.Reader) DecodeError!global_events.Event {')
        with emit.block():
            emit('const header = try reader.peek(10);')
            emit('const event_type = std.mem.readInt(u16, header[8..10], .native);')
            emit('return switch (event_type) {')
            with emit.block():
                for ev in xge_events:
                    orig = ev.orig or ev
                    emit(
                        f'{int(ev.number)} => .{{ .{prefix}{ev.name} = try {orig.name}Event.decode(reader) }},'
                    )
                geunknown = module.resolver.get('GeGenericEvent').decl_name
                emit(f'else => .{{ .GEUnknown = try {geunknown}.decode(reader) }},')
            emit('};')
        emit('}')
        emit()


def emit_events_module(modules: Sequence[Module], ext_import: str = '../_ext.zig') -> str:
    core_module = modules[0]
    emit = Emit()
    emit('// zig fmt: off')
    emit('// This file is generated by tools/genproto.py')
    emit()

    emit('const std = @import("std");')
    emit(f'const extensions = @import("{ext_import}");')
    emit('const DecodeError = @import("../_errors.zig").DecodeError;')
    for module in modules:
        if module.events:
            emit(f'const {module.name} = @import("{module.name}.zig");')
    emit()

    emit('pub const UnknownEvent = struct {')
    with emit.block():
        emit('code: u8,')
        emit('sequence: u16,')
        emit('raw: [32]u8,')
    emit('};')
    emit()

    emit('pub const Event = union(enum) {')
    with emit.block():
        emit('Unknown: UnknownEvent,')
        emit(f'GEUnknown: {core_module.name}.GeGenericEvent,')
        for module in modules:
            prefix = module.global_tagged_prefix()
            for ev in module.events.values():
                orig = ev.orig or ev
                emit(f'{prefix}{ev.name}: {module.name}.{orig.name}Event,')
    emit('};')
    emit()

    emit('pub const ExtensionEventSpec = struct {')
    with emit.block():
        emit('max_event_num: u8,')
        emit('decode: ?*const fn (*std.Io.Reader) DecodeError!Event,')
        emit('max_xge_event_num: u16,')
        emit('decode_xge: ?*const fn (*std.Io.Reader) DecodeError!Event,')
    emit('};')
    emit()

    for module in modules:
        if not module.events:
            continue
        normal_numbers = [it.number for it in module.events.values() if not it.xge]
        xge_numbers = [it.number for it in module.events.values() if it.xge]
        emit(f'const {module.name}_event_spec: ExtensionEventSpec = .{{')
        with emit.block():
            emit(f'.max_event_num = {max(normal_numbers, default=0)},')
            emit(f'.decode = {"%s.decodeEvent" % module.name if normal_numbers else "null"},')
            emit(f'.max_xge_event_num = {max(xge_numbers, default=0)},')
            emit(f'.decode_xge = {"%s.decodeXgeEvent" % module.name if xge_numbers else "null"},')
        emit('};')
        emit()

    emit('pub fn eventSpec(extension: extensions.Extension) ?*const ExtensionEventSpec {')
    with emit.block():
        emit('return switch (extension) {')
        with emit.block():
            for module in modules:
                if module.events:
                    emit(f'.{module.extension_enum_name()} => &{module.name}_event_spec,')
                else:
                    emit(f'.{module.extension_enum_name()} => null,')
        emit('};')
    emit('}')
    return emit.render()
