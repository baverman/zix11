const std = @import("std");
const io = @import("io.zig");
const toy = @import("gen/toy.zig");
const generated_events = @import("gen/events.zig");
const generated_errors = @import("gen/errors.zig");

var tmp: [256]u8 = undefined;

fn makePacket(buf: []u8, data: anytype) []const u8 {
    comptime var pos = 0;
    inline for(data) |it| {
        const T = std.meta.Elem(@TypeOf(it));
        const s = std.mem.sliceAsBytes(it);
        @memcpy(buf[pos..][0..s.len], s);
        pos += it.len * @sizeOf(T);
    }
    return buf[0..pos];
}


test "Point encode writes expected bytes" {
    const value = toy.Point{
        .x = 10,
        .y = 20,
        .serial = 30,
    };

    var buf: [16]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 9), writer.seek);
    try std.testing.expectEqual(@as(u8, 0), buf[0]);
    try std.testing.expectEqual(@as(i16, 10), std.mem.readInt(i16, buf[1..3], .native));
    try std.testing.expectEqual(@as(i16, 20), std.mem.readInt(i16, buf[3..5], .native));
    try std.testing.expectEqual(@as(u32, 30), std.mem.readInt(u32, buf[5..9], .native));
}

test "Point decode consumes crafted bytes" {
    const packet = makePacket(&tmp, .{ &[_]u8{0}, &[_]i16{10}, &[_]i16{20}, &[_]u32{30} });
    var reader: std.Io.Reader = .fixed(packet);
    const decoded = try toy.Point.decode(&reader);

    try std.testing.expectEqual(@as(i16, 10), decoded.x);
    try std.testing.expectEqual(@as(i16, 20), decoded.y);
    try std.testing.expectEqual(@as(u32, 30), decoded.serial);
}

test "ModeCount encode writes expected bytes" {
    const value = toy.ModeCount{
        .mode = .on,
        .count = 0x1234,
    };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 3), writer.seek);
    try std.testing.expectEqual(@as(u8, 1), buf[0]);
    try std.testing.expectEqual(@as(u16, 0x1234), std.mem.readInt(u16, buf[1..3], .native));
}

test "ModeCount decode consumes crafted bytes" {
    const packet = makePacket(&tmp, .{ &[_]u8{1}, &[_]u16{0x1234} });
    var reader: std.Io.Reader = .fixed(packet);
    const decoded = try toy.ModeCount.decode(&reader);

    try std.testing.expectEqual(toy.Mode.on, decoded.mode);
    try std.testing.expectEqual(@as(u16, 0x1234), decoded.count);
}

test "Tag encode writes expected bytes" {
    const value = toy.Tag{ .bytes = "ABCD".* };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 4), writer.seek);
    try std.testing.expectEqualSlices(u8, "ABCD", buf[0..4]);
}

test "Tag decode consumes crafted bytes" {
    var reader: std.Io.Reader = .fixed("ABCD");
    const decoded = try toy.Tag.decode(&reader);

    try std.testing.expectEqualStrings("ABCD", decoded.bytes[0..]);
}

test "AliasHolder encode and decode use the final scalar type" {
    const value = toy.AliasHolder{
        .visual = 0x01020304,
    };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 4), writer.seek);
    try std.testing.expectEqual(@as(u32, 0x01020304), std.mem.readInt(u32, buf[0..4], .native));

    const packet = makePacket(&tmp, .{&[_]u32{0x01020304}});
    var reader: std.Io.Reader = .fixed(packet);
    const decoded = try toy.AliasHolder.decode(&reader);

    try std.testing.expectEqual(@as(u32, 0x01020304), decoded.visual);
}

test "DrawableHolder encode and decode use the xidunion shape" {
    const raw_value = toy.DrawableHolder{
        .drawable = .{ .raw = 0x01020304 },
    };
    const window_value = toy.DrawableHolder{
        .drawable = .{ .window = @enumFromInt(0x11121314) },
    };
    const pixmap_value = toy.DrawableHolder{
        .drawable = .{ .pixmap = @enumFromInt(0x21222324) },
    };

    var raw_buf: [8]u8 = undefined;
    var raw_writer = io.FixedBufferWriter.init(&raw_buf);
    try raw_value.encode(&raw_writer);
    try std.testing.expectEqual(@as(u32, 0x01020304), std.mem.readInt(u32, raw_buf[0..4], .native));
    try std.testing.expectEqual(@as(u32, 0x01020304), raw_value.drawable.toInt());

    var window_buf: [8]u8 = undefined;
    var window_writer = io.FixedBufferWriter.init(&window_buf);
    try window_value.encode(&window_writer);
    try std.testing.expectEqual(@as(u32, 0x11121314), std.mem.readInt(u32, window_buf[0..4], .native));
    try std.testing.expectEqual(@as(u32, 0x11121314), window_value.drawable.toInt());

    var pixmap_buf: [8]u8 = undefined;
    var pixmap_writer = io.FixedBufferWriter.init(&pixmap_buf);
    try pixmap_value.encode(&pixmap_writer);
    try std.testing.expectEqual(@as(u32, 0x21222324), std.mem.readInt(u32, pixmap_buf[0..4], .native));
    try std.testing.expectEqual(@as(u32, 0x21222324), pixmap_value.drawable.toInt());

    const packet = makePacket(&tmp, .{&[_]u32{0x31323334}});
    var reader: std.Io.Reader = .fixed(packet);
    const decoded = try toy.DrawableHolder.decode(&reader);

    switch (decoded.drawable) {
        .raw => |it| try std.testing.expectEqual(@as(u32, 0x31323334), it),
        else => return error.UnexpectedPayload,
    }
}

test "ClientData exposes raw and typed fixed-size views" {
    const data8 = toy.ClientData.fromData8("ABCD".*);
    try std.testing.expectEqualSlices(u8, "ABCD", data8.asRaw()[0..]);
    try std.testing.expectEqualDeep(@as([4]u8, "ABCD".*), try data8.asData8());

    const data16 = toy.ClientData.fromData16(.{ 0x1122, 0x3344 });
    try std.testing.expectEqualDeep(@as([2]u16, .{ 0x1122, 0x3344 }), try data16.asData16());

    const data32 = toy.ClientData.fromData32(.{0x01020304});
    try std.testing.expectEqualDeep(@as([1]u32, .{0x01020304}), try data32.asData32());
}

test "ClientDataHolder encode and decode treat union field as raw bytes" {
    const value = toy.ClientDataHolder{
        .data = toy.ClientData.fromData8("WXYZ".*),
    };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 4), writer.seek);
    try std.testing.expectEqualSlices(u8, "WXYZ", buf[0..4]);

    var reader: std.Io.Reader = .fixed("WXYZ");
    const decoded = try toy.ClientDataHolder.decode(&reader);

    try std.testing.expectEqualDeep(@as([4]u8, "WXYZ".*), try decoded.data.asData8());
}

test "generated errors decode error and errorcopy tags" {
    const raw: generated_errors.ProtocolError = .{
        .code = 1,
        .sequence = 17,
        .bad_value = 0xdeadbeef,
        .minor_opcode = 0,
        .major_opcode = 0,
        .tail = [_]u8{0} ** 20,
    };

    switch (generated_errors.decodeCoreError(1, raw).?) {
        .Request => |it| {
            try std.testing.expectEqual(@as(u8, 1), it.code);
            try std.testing.expectEqual(@as(u32, 0xdeadbeef), it.bad_value);
        },
        else => return error.TestUnexpectedResult,
    }

    switch (generated_errors.decodeCoreError(2, raw).?) {
        .Value => |it| try std.testing.expectEqual(@as(u8, 1), it.code),
        else => return error.TestUnexpectedResult,
    }
}

test "generated events decode normal event and eventcopy tags" {
    const notify_packet = makePacket(&tmp, .{
        &[_]u8{ 1, 9 },
        &[_]u16{0x1234},
        &[_]u16{0x5566},
        &[_]u8{0} ** 25,
    });
    var notify_reader: std.Io.Reader = .fixed(notify_packet);
    switch (try toy.decodeEvent(&notify_reader)) {
        .SimpleNotify => |it| {
            try std.testing.expectEqual(@as(u8, 9), it.detail);
            try std.testing.expectEqual(@as(u16, 0x5566), it.count);
        },
        else => return error.TestUnexpectedResult,
    }

    const copy_packet = makePacket(&tmp, .{
        &[_]u8{ 2, 7 },
        &[_]u16{0x5678},
        &[_]u16{0x1122},
        &[_]u8{0} ** 25,
    });
    var copy_reader: std.Io.Reader = .fixed(copy_packet);
    switch (try toy.decodeEvent(&copy_reader)) {
        .SimpleNotifyCopy => |it| {
            try std.testing.expectEqual(@as(u8, 7), it.detail);
            try std.testing.expectEqual(@as(u16, 0x1122), it.count);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "generated events decode xge event and eventcopy tags" {
    const notify_packet = makePacket(&tmp, .{
        &[_]u8{ 35, 42 },
        &[_]u16{0x1234},
        &[_]u32{0},
        &[_]u16{7},
        &[_]u16{0x3344},
        &[_]u8{0} ** 20,
    });
    var notify_reader: std.Io.Reader = .fixed(notify_packet);
    switch (try toy.decodeXgeEvent(&notify_reader)) {
        .InfoNotify => |it| {
            try std.testing.expectEqual(@as(u8, 42), it.extension);
            try std.testing.expectEqual(@as(u32, 0), it.length);
            try std.testing.expectEqual(@as(u16, 7), it.event_type);
            try std.testing.expectEqual(@as(u16, 0x3344), it.count);
        },
        else => return error.TestUnexpectedResult,
    }

    const copy_packet = makePacket(&tmp, .{
        &[_]u8{ 35, 42 },
        &[_]u16{0x5678},
        &[_]u32{0},
        &[_]u16{8},
        &[_]u16{0x7788},
        &[_]u8{0} ** 20,
    });
    var copy_reader: std.Io.Reader = .fixed(copy_packet);
    switch (try toy.decodeXgeEvent(&copy_reader)) {
        .InfoNotifyCopy => |it| {
            try std.testing.expectEqual(@as(u8, 42), it.extension);
            try std.testing.expectEqual(@as(u16, 8), it.event_type);
            try std.testing.expectEqual(@as(u16, 0x7788), it.count);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "Blob encode writes expected bytes" {
    const value = toy.Blob{
        .bytes = "xyz",
    };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 5), writer.seek);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, buf[0..2], .native));
    try std.testing.expectEqualSlices(u8, "xyz", buf[2..5]);
}

test "Blob decode allocates and deinit frees" {
    const packet = makePacket(&tmp, .{&[_]u16{3}, "xyz"});
    var reader: std.Io.Reader = .fixed(packet);
    var decoded = try toy.Blob.decode(std.testing.allocator, &reader);
    defer decoded.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("xyz", decoded.bytes);
}

test "RepeatedLike encode and decode keep single-field arithmetic count public" {
    const value = toy.RepeatedLike{
        .count = 1,
        .items = &[_]u32{ 1, 2, 3, 4 },
    };

    var buf: [32]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 17), writer.seek);
    try std.testing.expectEqual(@as(u8, 1), buf[0]);
    try std.testing.expectEqual(@as(u32, 1), std.mem.readInt(u32, buf[1..5], .native));
    try std.testing.expectEqual(@as(u32, 4), std.mem.readInt(u32, buf[13..17], .native));

    const packet = makePacket(&tmp, .{
        &[_]u8{1},
        &[_]u32{ 1, 2, 3, 4 },
    });
    var reader: std.Io.Reader = .fixed(packet);
    var decoded = try toy.RepeatedLike.decode(std.testing.allocator, &reader);
    defer decoded.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(u8, 1), decoded.count);
    try std.testing.expectEqual(@as(usize, 4), decoded.items.len);
    try std.testing.expectEqual(@as(u32, 1), decoded.items[0]);
    try std.testing.expectEqual(@as(u32, 4), decoded.items[3]);
}

test "KeysymsLike encode and decode keep multi-field expression inputs public" {
    const value = toy.KeysymsLike{
        .count = 2,
        .stride = 2,
        .items = &[_]u32{ 1, 2, 3, 4 },
    };

    var buf: [32]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 18), writer.seek);
    try std.testing.expectEqual(@as(u8, 2), buf[0]);
    try std.testing.expectEqual(@as(u8, 2), buf[1]);
    try std.testing.expectEqual(@as(u32, 1), std.mem.readInt(u32, buf[2..6], .native));
    try std.testing.expectEqual(@as(u32, 4), std.mem.readInt(u32, buf[14..18], .native));

    const packet = makePacket(&tmp, .{
        &[_]u8{2},
        &[_]u8{2},
        &[_]u32{ 1, 2, 3, 4 },
    });
    var reader: std.Io.Reader = .fixed(packet);
    var decoded = try toy.KeysymsLike.decode(std.testing.allocator, &reader);
    defer decoded.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(u8, 2), decoded.count);
    try std.testing.expectEqual(@as(u8, 2), decoded.stride);
    try std.testing.expectEqual(@as(usize, 4), decoded.items.len);
    try std.testing.expectEqual(@as(u32, 1), decoded.items[0]);
    try std.testing.expectEqual(@as(u32, 4), decoded.items[3]);
}

test "TailBytes encode and decode consume the remaining payload" {
    const value = toy.TailBytes{
        .bytes = "tail",
    };

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 4), writer.seek);
    try std.testing.expectEqualSlices(u8, "tail", buf[0..4]);

    var reader: std.Io.Reader = .fixed("tail");
    var decoded = try toy.TailBytes.decode(std.testing.allocator, &reader);
    defer decoded.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("tail", decoded.bytes);
}

test "TailPoints encode and decode consume typed items to the end" {
    var points = [_]toy.Point{
        .{ .x = 10, .y = 20, .serial = 30 },
        .{ .x = 40, .y = 50, .serial = 60 },
    };
    const value = toy.TailPoints{
        .points = points[0..],
    };

    var buf: [32]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 18), writer.seek);
    try std.testing.expectEqual(@as(u8, 0), buf[0]);
    try std.testing.expectEqual(@as(i16, 10), std.mem.readInt(i16, buf[1..3], .native));
    try std.testing.expectEqual(@as(u32, 60), std.mem.readInt(u32, buf[14..18], .native));

    const packet = makePacket(&tmp, .{
        &[_]u8{0},
        &[_]i16{10},
        &[_]i16{20},
        &[_]u32{30},
        &[_]u8{0},
        &[_]i16{40},
        &[_]i16{50},
        &[_]u32{60},
    });
    var reader: std.Io.Reader = .fixed(packet);
    var decoded = try toy.TailPoints.decode(std.testing.allocator, &reader);
    defer decoded.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 2), decoded.points.len);
    try std.testing.expectEqual(@as(i16, 10), decoded.points[0].x);
    try std.testing.expectEqual(@as(u32, 30), decoded.points[0].serial);
    try std.testing.expectEqual(@as(i16, 40), decoded.points[1].x);
    try std.testing.expectEqual(@as(u32, 60), decoded.points[1].serial);
}

test "ModePayload encode writes expected bytes" {
    const on_value = toy.ModePayload{
        .payload = .{ .on = .{ .count = 0x1234 } },
    };

    var on_buf: [8]u8 = undefined;
    var on_writer = io.FixedBufferWriter.init(&on_buf);
    try on_value.encode(&on_writer);

    try std.testing.expectEqual(@as(usize, 3), on_writer.seek);
    try std.testing.expectEqual(@as(u8, 1), on_buf[0]);
    try std.testing.expectEqual(@as(u16, 0x1234), std.mem.readInt(u16, on_buf[1..3], .native));

    const off_blob = "blob";
    const off_value = toy.ModePayload{
        .payload = .{ .off = .{
            .blob = off_blob,
        } },
    };

    var off_buf: [8]u8 = undefined;
    var off_writer = io.FixedBufferWriter.init(&off_buf);
    try off_value.encode(&off_writer);

    try std.testing.expectEqual(@as(usize, 6), off_writer.seek);
    try std.testing.expectEqual(@as(u8, 0), off_buf[0]);
    try std.testing.expectEqual(@as(u8, 4), off_buf[1]);
    try std.testing.expectEqualSlices(u8, "blob", off_buf[2..6]);
}

test "ModePayload decode consumes crafted bytes" {
    const on_packet = makePacket(&tmp, .{ &[_]u8{1}, &[_]u16{0x1234} });
    var on_reader: std.Io.Reader = .fixed(on_packet);
    var on_decoded = try toy.ModePayload.decode(std.testing.allocator, &on_reader);
    defer on_decoded.deinit(std.testing.allocator);

    switch (on_decoded.payload) {
        .on => |it| try std.testing.expectEqual(@as(u16, 0x1234), it.count),
        else => return error.UnexpectedPayload,
    }

    const off_packet = makePacket(&tmp, .{ &[_]u8{0}, &[_]u8{4}, "blob" });
    var off_reader: std.Io.Reader = .fixed(off_packet);
    var off_decoded = try toy.ModePayload.decode(std.testing.allocator, &off_reader);
    defer off_decoded.deinit(std.testing.allocator);

    switch (off_decoded.payload) {
        .off => |it| {
            try std.testing.expectEqualStrings("blob", it.blob);
        },
        else => return error.UnexpectedPayload,
    }
}

test "BitPayload encode and decode use mask-driven optional arms" {
    const value = toy.BitPayload{
        .payload = .{
            .id = 0x01020304,
            .counted = .{ .count = 0x1122 },
        },
    };

    var buf: [16]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 9), writer.seek);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, buf[0..2], .native));
    try std.testing.expectEqual(@as(u32, 0x01020304), std.mem.readInt(u32, buf[2..6], .native));
    try std.testing.expectEqual(@as(u8, 0), buf[6]);
    try std.testing.expectEqual(@as(u16, 0x1122), std.mem.readInt(u16, buf[7..9], .native));

    const packet = makePacket(&tmp, .{ &[_]u16{3}, &[_]u32{0x01020304}, &[_]u8{0}, &[_]u16{0x1122} });
    var reader: std.Io.Reader = .fixed(packet);
    const decoded = try toy.BitPayload.decode(&reader);

    try std.testing.expectEqual(@as(?u32, 0x01020304), decoded.payload.id);
    try std.testing.expect(decoded.payload.counted != null);
    try std.testing.expectEqual(@as(u16, 0x1122), decoded.payload.counted.?.count);
}

test "UseByteField header byte and encode" {
    const req = toy.UseByteField{
        .mode = .on,
        .count = 0x1122,
    };

    try std.testing.expectEqual(@as(u8, 1), toy.UseByteField.opcode);
    try std.testing.expectEqual(@as(u8, 1), req.headerByte1());

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try req.encode(&writer);

    try std.testing.expectEqual(@as(usize, 2), writer.seek);
    try std.testing.expectEqual(@as(u16, 0x1122), std.mem.readInt(u16, buf[0..2], .native));
}

test "UseBytePad header byte and encode" {
    const req = toy.UseBytePad{
        .count = 0x3344,
    };

    try std.testing.expectEqual(@as(u8, 2), toy.UseBytePad.opcode);
    try std.testing.expectEqual(@as(u8, 0), req.headerByte1());

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try req.encode(&writer);

    try std.testing.expectEqual(@as(usize, 2), writer.seek);
    try std.testing.expectEqual(@as(u16, 0x3344), std.mem.readInt(u16, buf[0..2], .native));
}

test "UseCard32 leaves header byte zero and encodes payload" {
    const req = toy.UseCard32{
        .id = 0x01020304,
    };

    try std.testing.expectEqual(@as(u8, 3), toy.UseCard32.opcode);
    try std.testing.expectEqual(@as(u8, 0), req.headerByte1());

    var buf: [8]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try req.encode(&writer);

    try std.testing.expectEqual(@as(usize, 4), writer.seek);
    try std.testing.expectEqual(@as(u32, 0x01020304), std.mem.readInt(u32, buf[0..4], .native));
}

test "UseByteField reply decode accepts byte1 from caller" {
    var packet = [_]u8{ 0x34, 0x12 };
    var reader: std.Io.Reader = .fixed(&packet);
    const reply = try toy.UseByteField.Reply.decode(&reader, 7);

    try std.testing.expectEqual(@as(u8, 7), reply.status);
    try std.testing.expectEqual(@as(u16, 0x1234), reply.count);
}

test "UseBytePad reply decode ignores byte1 and reads payload" {
    var packet = [_]u8{ 0x78, 0x56 };
    var reader: std.Io.Reader = .fixed(&packet);
    const reply = try toy.UseBytePad.Reply.decode(&reader, 99);

    try std.testing.expectEqual(@as(u16, 0x5678), reply.count);
}

test "UseCard32 reply decode ignores byte1 and reads payload" {
    const packet = makePacket(&tmp, .{&[_]u32{0x01020304}});
    var reader: std.Io.Reader = .fixed(packet);
    const reply = try toy.UseCard32.Reply.decode(&reader, 17);

    try std.testing.expectEqual(@as(u32, 0x01020304), reply.id);
}

test "BlobList encode writes expected bytes" {
    var blobs = [_]toy.Blob{
        .{ .bytes = "bo" },
        .{ .bytes = "moo" },
    };
    const value = toy.BlobList{
        .blobs = blobs[0..],
    };

    var buf: [16]u8 = undefined;
    var writer = io.FixedBufferWriter.init(&buf);
    try value.encode(&writer);

    try std.testing.expectEqual(@as(usize, 11), writer.seek);
    try std.testing.expectEqual(@as(u16, 2), std.mem.readInt(u16, buf[0..2], .native));
    try std.testing.expectEqual(@as(u16, 2), std.mem.readInt(u16, buf[2..4], .native));
    try std.testing.expectEqualSlices(u8, "bo", buf[4..6]);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, buf[6..8], .native));
    try std.testing.expectEqualSlices(u8, "moo", buf[8..11]);
}

test "BlobList decode consumes crafted bytes" {
    const packet = makePacket(&tmp, .{&[_]u16{2}, &[_]u16{2}, "bo", &[_]u16{3}, "moo"});
    var reader: std.Io.Reader = .fixed(packet);
    var result = try toy.BlobList.decode(std.testing.allocator, &reader);
    defer result.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("bo", result.blobs[0].bytes);
    try std.testing.expectEqualStrings("moo", result.blobs[1].bytes);
}
