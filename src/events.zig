const std = @import("std");
const ext = @import("ext.zig");
const generated = @import("gen/events.zig");
const x = @import("gen/xproto.zig");

pub const Event = generated.Event;
pub const UnknownEvent = generated.UnknownEvent;
pub const ExtensionEventSpec = generated.ExtensionEventSpec;
pub const eventSpec = generated.eventSpec;
pub const DecodeError = @import("_errors.zig").DecodeError;

pub fn decodeEvent(
    registered_extensions: *std.enums.EnumMap(ext.Extension, ext.ExtensionInfo),
    packet: []const u8,
) DecodeError!Event {
    var raw: [32]u8 = undefined;
    std.debug.assert(packet.len >= 32);
    @memcpy(raw[0..], packet[0..32]);

    const wire_code = raw[0] & 0x7f;
    if (wire_code == 35) {
        const extension_opcode = raw[1];
        var xge_it = registered_extensions.iterator();
        while (xge_it.next()) |entry| {
            const info = entry.value;
            const spec = info.event_spec orelse continue;
            const decode_xge = spec.decode_xge orelse continue;
            if (extension_opcode == info.major_opcode) {
                var reader: std.Io.Reader = .fixed(packet);
                return try decode_xge(&reader);
            }
        }
    }

    var it = registered_extensions.iterator();
    while (it.next()) |entry| {
        const info = entry.value;
        const spec = info.event_spec orelse continue;
        const decode = spec.decode orelse continue;
        if (wire_code >= info.first_event and wire_code <= info.first_event + spec.max_event_num) {
            if (wire_code == 35 and info.first_event == 0 and packet.len > raw.len) {
                var reader: std.Io.Reader = .fixed(packet);
                return try decode(&reader);
            }
            // Extension decoders expect a local 0-based event code; keep bit 7 unchanged.
            raw[0] = (raw[0] & 0x80) | (wire_code - info.first_event);
            var reader: std.Io.Reader = .fixed(&raw);
            return try decode(&reader);
        }
    }

    return .{ .Unknown = .{
        .code = wire_code,
        .sequence = std.mem.readInt(u16, raw[2..4], .native),
        .raw = raw,
    } };
}

pub fn clientMessageData(comptime T: type, data: []const T) x.ClientMessageData {
    var raw = std.mem.zeroes([20]u8);
    const bdata = std.mem.sliceAsBytes(data);
    const len = @min(raw.len, bdata.len);
    @memcpy(raw[0..len], bdata[0..len]);
    return x.ClientMessageData.fromData8(raw);
}
