from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Sequence

from . import xcbxml
from .common import Emit, Field, Resolver, emit_decl_items, items_size
from .fields import build_items, get_byte_slot

if TYPE_CHECKING:
    from . import Module


@dataclass(frozen=True)
class EventType:
    name: str
    number: int
    xge: bool
    no_sequence_number: bool
    items: tuple[Field, ...]
    orig: EventType | None = None

    @staticmethod
    def from_schema(event: xcbxml.Event, resolver: Resolver) -> EventType:
        items = build_items(event.fields, resolver, event.name)
        if items_size(items) == 'dyn':
            raise NotImplementedError('dynamic events are not supported')
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
        emit(f'pub const {self.name}Event = struct {{')
        with emit.block():
            if self.xge:
                emit('extension: u8,')
                emit('length: u32,')
                emit('event_type: u16,')
            emit_decl_items(emit, self.items)
            emit()
            emit('pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {')
            with emit.block():
                emit('var result: @This() = undefined;')
                if self.no_sequence_number:
                    for item in self.items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                elif self.xge:
                    emit('_ = try reader.takeByte();')
                    emit('result.extension = try reader.takeByte();')
                    emit('_ = try reader.takeInt(u16, .native);')
                    emit('result.length = try reader.takeInt(u32, .native);')
                    emit('result.event_type = try reader.takeInt(u16, .native);')
                    emit('const payload_start_seek = reader.seek;')
                    for item in self.items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
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
                        body_items = ()
                    emit('_ = try reader.takeInt(u16, .native);')
                    for item in body_items:
                        item.type.emit_decode(emit, item.decode_target_expr('result'))
                emit('return result;')
            emit('}')
        emit('};')
        emit()


# TODO: replace with wire implementation
def emit_ge_generic_event_definition(emit: Emit) -> None:
    emit('pub const GeGenericEvent = struct {')
    with emit.block():
        emit('extension: u8,')
        emit('length: u32,')
        emit('event_type: u16,')
        emit()
        emit('pub fn decode(reader: *std.Io.Reader) DecodeError!@This() {')
        with emit.block():
            emit('_ = try reader.takeByte();')
            emit('const extension = try reader.takeByte();')
            emit('_ = try reader.takeInt(u16, .native);')
            emit('const length = try reader.takeInt(u32, .native);')
            emit('const event_type = try reader.takeInt(u16, .native);')
            emit('const payload_start_seek = reader.seek;')
            emit('_ = try reader.take(22);')
            emit('const xge_body_len = reader.seek - payload_start_seek;')
            emit('const total_body_len = 22 + @as(usize, length) * 4;')
            emit(
                'if (xge_body_len < total_body_len) _ = try reader.take(total_body_len - xge_body_len);'
            )
            emit('return .{')
            with emit.block():
                emit('.extension = extension,')
                emit('.length = length,')
                emit('.event_type = event_type,')
            emit('};')
        emit('}')
    emit('};')
    emit()


def emit_definitions(emit: Emit, events: Sequence[EventType]) -> None:
    for ev in events:
        if not ev.orig:
            ev.emit_definition(emit)

    normal_events = [it for it in events if not it.xge]
    xge_events = [it for it in events if it.xge]

    if xge_events:
        emit_ge_generic_event_definition(emit)

    if normal_events:
        emit('pub fn decodeEvent(reader: *std.Io.Reader) DecodeError!global_events.Event {')
        with emit.block():
            emit('const code = (try reader.peek(1))[0] & 0x7f;')
            emit('return switch (code) {')
            with emit.block():
                for ev in normal_events:
                    orig = ev.orig or ev
                    emit(
                        f'{int(ev.number)} => .{{ .{ev.name} = try {orig.name}Event.decode(reader) }},'
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
                        f'{int(ev.number)} => .{{ .{ev.name} = try {orig.name}Event.decode(reader) }},'
                    )
                emit('else => .{ .GEUnknown = try GeGenericEvent.decode(reader) },')
            emit('};')
        emit('}')
        emit()


def emit_events_module(bindings: xcbxml.Bindings, module: Module) -> str:
    emit = Emit()
    emit('// zig fmt: off')
    emit('// This file is generated by tools/genproto.py')
    emit()
    emit('const std = @import("std");')
    emit('const extensions = @import("../_ext.zig");')
    emit('const DecodeError = @import("../_errors.zig").DecodeError;')
    emit(f'const current = @import("{module.header}.zig");')
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
        emit('GEUnknown: current.GeGenericEvent,')
        for ev in module.events.values():
            orig = ev.orig or ev
            emit(f'{ev.name}: current.{orig.name}Event,')
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
    normal_numbers = [it.number for it in module.events.values() if not it.xge]
    xge_numbers = [it.number for it in module.events.values() if it.xge]
    emit('const current_event_spec: ExtensionEventSpec = .{')
    with emit.block():
        emit(f'.max_event_num = {max(normal_numbers, default=0)},')
        emit(f'.decode = {"current.decodeEvent" if normal_numbers else "null"},')
        emit(f'.max_xge_event_num = {max(xge_numbers, default=0)},')
        emit(f'.decode_xge = {"current.decodeXgeEvent" if xge_numbers else "null"},')
    emit('};')
    emit()
    emit('pub fn eventSpec(extension: extensions.Extension) ?*const ExtensionEventSpec {')
    with emit.block():
        if bindings.header == 'xproto':
            emit('return switch (extension) {')
            with emit.block():
                emit('.CORE => &current_event_spec,')
                emit('else => null,')
            emit('};')
        else:
            emit('_ = extension;')
            emit('return null;')
    emit('}')
    return emit.render()
