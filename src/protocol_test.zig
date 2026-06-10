const std = @import("std");
const events = @import("events.zig");
const ext = @import("ext.zig");
const protocol = @import("protocol.zig");
const x = @import("gen/xproto.zig");
const makePacket = @import("test_helpers.zig").makePacket;

var tmp: [256]u8 = undefined;

test "Protocol.send frames core requests with opcode and header byte 1" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var buf: [64]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = x.InternAtom{
        .only_if_exists = true,
        .name = "WM_NAME",
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(1, sequence);
    try std.testing.expectEqual(x.InternAtom.opcode, packet[0]);
    try std.testing.expectEqual(req.headerByte1(), packet[1]);
    try std.testing.expectEqual(4, std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(16, packet.len);
    try std.testing.expectEqualSlices(u8, "WM_NAME", packet[8..15]);
    try std.testing.expectEqual(0, packet[15]);
}

test "Protocol.send frames MIT-SHM requests with registered major opcode and request opcode" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.MIT_SHM, .{
        .major_opcode = 137,
        .first_event = 64,
        .first_error = 128,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);

    const sequence = try proto.send(&writer, ext.shm.QueryVersion{}, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(1, sequence);
    try std.testing.expectEqual(137, packet[0]);
    try std.testing.expectEqual(ext.shm.QueryVersion.opcode, packet[1]);
    try std.testing.expectEqual(1, std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(4, packet.len);
}

test "Protocol.send frames RENDER requests with registered major opcode and padded length" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.RENDER, .{
        .major_opcode = 138,
        .first_event = 96,
        .first_error = 160,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = ext.render.QueryVersion{
        .client_major_version = 0,
        .client_minor_version = 11,
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(1, sequence);
    try std.testing.expectEqual(138, packet[0]);
    try std.testing.expectEqual(ext.render.QueryVersion.opcode, packet[1]);
    try std.testing.expectEqual(3, std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(0, std.mem.readInt(u32, packet[4..8], .native));
    try std.testing.expectEqual(11, std.mem.readInt(u32, packet[8..12], .native));
    try std.testing.expectEqual(12, packet.len);
}

test "Protocol.send frames XFIXES requests with registered major opcode and request opcode" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XFIXES, .{
        .major_opcode = 139,
        .first_event = 110,
        .first_error = 170,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = ext.xfixes.QueryVersion{
        .client_major_version = 6,
        .client_minor_version = 0,
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(1, sequence);
    try std.testing.expectEqual(139, packet[0]);
    try std.testing.expectEqual(ext.xfixes.QueryVersion.opcode, packet[1]);
    try std.testing.expectEqual(3, std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(6, std.mem.readInt(u32, packet[4..8], .native));
    try std.testing.expectEqual(0, std.mem.readInt(u32, packet[8..12], .native));
    try std.testing.expectEqual(12, packet.len);
}

test "Protocol.readEvent decodes registered XFIXES events into global Event" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XFIXES, .{
        .major_opcode = 139,
        .first_event = 110,
        .first_error = 170,
        .event_spec = events.eventSpec(.XFIXES),
    });

    const packet = makePacket(&tmp, .{ &[_]u8{ 110, 0 }, &[_]u16{21}, &[_]u8{0} ** 28 });

    var reader: std.Io.Reader = .fixed(packet);
    const event = try proto.readEvent(&reader);

    switch (event) {
        .XFixesSelectionNotify => |ev| try std.testing.expectEqual(ext.xfixes.SelectionEvent.SetSelectionOwner, ev.subtype),
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.pendingEvent decodes queued core events into global Event" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const packet = makePacket(&tmp, .{ &[_]u8{ 12, 0 }, &[_]u16{9}, &[_]u8{0} ** 12, &[_]u16{4}, &[_]u8{0} ** 14 });
    try proto.pending_events.pushBack(std.testing.allocator, .{
        .fixed = .{
            .data = blk: {
                var raw = std.mem.zeroes([64]u8);
                @memcpy(raw[0..packet.len], packet);
                break :blk raw;
            },
            .len = packet.len,
        },
    });

    const event = (try proto.pendingEvent()) orelse return error.TestUnexpectedResult;
    switch (event) {
        .Expose => |ev| try std.testing.expectEqual(4, ev.count),
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.pendingEvent preserves queued GE packet length" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const packet = makePacket(&tmp, .{ &[_]u8{ 35, 42 }, &[_]u16{17}, &[_]u32{0}, &[_]u16{99}, &[_]u8{0} ** 28 });

    try proto.queueEventPacket(packet);

    const event = (try proto.pendingEvent()) orelse return error.TestUnexpectedResult;
    switch (event) {
        .GEUnknown => |ev| {
            try std.testing.expectEqual(42, ev.extension);
            try std.testing.expectEqual(0, ev.length);
            try std.testing.expectEqual(99, ev.event_type);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.readEvent decodes XInputMotion XGE packets" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XINPUT, .{
        .major_opcode = 131,
        .first_event = 64,
        .first_error = 128,
        .event_spec = events.eventSpec(.XINPUT),
    });

    const packet = makePacket(&tmp, .{
        &[_]u8{ 35, 131 },
        &[_]u16{17},
        &[_]u32{17},
        &[_]u16{6},
        &[_]u16{12},
        &[_]u32{0x01020304},
        &[_]u32{9},
        &[_]u32{0x11111111},
        &[_]u32{0x22222222},
        &[_]u32{0x33333333},
        &[_]i32{10 << 16},
        &[_]i32{20 << 16},
        &[_]i32{30 << 16},
        &[_]i32{40 << 16},
        &[_]u16{1},
        &[_]u16{1},
        &[_]u16{13},
        &[_]u8{ 0, 0 },
        &[_]u32{0x00010000},
        &[_]u32{1},
        &[_]u32{2},
        &[_]u32{3},
        &[_]u32{4},
        &[_]u8{ 5, 6, 7, 8 },
        &[_]u32{0x10},
        &[_]u32{0x1},
        &[_]i32{50},
        &[_]u32{0x80000000},
        &[_]u8{0} ** 4,
    });

    var reader: std.Io.Reader = .fixed(packet);
    const event = try proto.readEvent(&reader);

    switch (event) {
        .InputMotion => |ev| {
            try std.testing.expectEqual(131, ev.extension);
            try std.testing.expectEqual(17, ev.length);
            try std.testing.expectEqual(6, ev.event_type);
            try std.testing.expectEqual(12, ev.deviceid);
            try std.testing.expectEqual(0x01020304, ev.time);
            try std.testing.expectEqual(9, ev.detail);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x11111111)), ev.root);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x22222222)), ev.event);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x33333333)), ev.child);
            try std.testing.expectEqual(10 << 16, ev.root_x);
            try std.testing.expectEqual(20 << 16, ev.root_y);
            try std.testing.expectEqual(30 << 16, ev.event_x);
            try std.testing.expectEqual(40 << 16, ev.event_y);
            try std.testing.expectEqual(1, ev.buttons_len);
            try std.testing.expectEqual(1, ev.valuators_len);
            try std.testing.expectEqual(13, ev.sourceid);
            try std.testing.expectEqual(0x00010000, ev.flags);
            try std.testing.expectEqual(4, ev.mods.effective);
            try std.testing.expectEqual(8, ev.group.effective);

            var body = try ev.getBody(std.testing.allocator);
            defer body.deinit(std.testing.allocator);
            try std.testing.expectEqual(1, body.button_mask.len);
            try std.testing.expectEqual(1, body.valuator_mask.len);
            try std.testing.expectEqual(1, body.axisvalues.len);
            try std.testing.expectEqual(0x10, body.button_mask[0]);
            try std.testing.expectEqual(0x1, body.valuator_mask[0]);
            try std.testing.expectEqual(50, body.axisvalues[0].integral);
            try std.testing.expectEqual(0x80000000, body.axisvalues[0].frac);
        },
        else => return error.TestUnexpectedResult,
    }
}
