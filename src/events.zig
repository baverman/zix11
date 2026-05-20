const std = @import("std");
const generated = @import("gen/events.zig");
const x = @import("gen/xproto.zig");

pub const Event = generated.Event;
pub const UnknownEvent = generated.UnknownEvent;
pub const ExtensionEventSpec = generated.ExtensionEventSpec;
pub const eventSpec = generated.eventSpec;
pub const wrapEvent = generated.wrapEvent;

pub fn clientMessageData(comptime T: type, data: []const T) x.ClientMessageData {
    var result: x.ClientMessageData = .{ .data8 = std.mem.zeroes([20]u8) };
    const bdata = std.mem.sliceAsBytes(data);
    const len = @min(result.data8.len, bdata.len);
    @memcpy(result.data8[0..len], bdata[0..len]);
    return result;
}
