const std = @import("std");
const native_endian = @import("builtin").cpu.arch.endian();

pub const CountingWriter = struct {
    seek: usize = 0,

    pub fn init() @This() {
        return .{};
    }

    pub fn write(self: *@This(), bytes: []const u8) void {
        self.seek += bytes.len;
    }

    pub fn writeByte(self: *@This(), _: u8) void {
        self.seek += 1;
    }

    pub fn splatByte(self: *@This(), _: u8, n: usize) void {
        self.seek += n;
    }

    pub fn writeInt(self: *@This(), comptime T: type, _: T) void {
        self.seek += @sizeOf(T);
    }
};

pub const FixedBufferWriter = struct {
    buf: []u8,
    seek: usize = 0,

    pub fn init(buf: []u8) @This() {
        return .{ .buf = buf };
    }

    pub fn write(self: *@This(), bytes: []const u8) void {
        @memcpy(self.buf[self.seek..][0..bytes.len], bytes);
        self.seek += bytes.len;
    }

    pub fn writeByte(self: *@This(), byte: u8) void {
        self.buf[self.seek] = byte;
        self.seek += 1;
    }

    pub fn splatByte(self: *@This(), byte: u8, n: usize) void {
        @memset(self.buf[self.seek..][0..n], byte);
        self.seek += n;
    }

    pub fn writeInt(self: *@This(), comptime T: type, value: T) void {
        std.mem.writeInt(T, self.buf[self.seek..][0..@sizeOf(T)], value, native_endian);
        self.seek += @sizeOf(T);
    }
};

fn encodeExamplePacket(writer: anytype) void {
    writer.writeByte(0xaa);
    writer.writeInt(u16, 0x1122);
    const pad = (4 - (writer.seek % 4)) % 4;
    writer.splatByte(0, pad);
    writer.write("zig");
    writer.splatByte(0xff, 2);
}

fn encodeRequest(writer: anytype, payload: []const u8) void {
    const len_offset = writer.seek + 2;
    writer.writeByte(99);
    writer.writeByte(7);
    writer.writeInt(u16, 0);
    writer.write(payload);
    const pad = (4 - (writer.seek % 4)) % 4;
    writer.splatByte(0, pad);
    if (@TypeOf(writer.*) == FixedBufferWriter) {
        std.mem.writeInt(u16, writer.buf[len_offset..][0..2], @intCast(writer.seek / 4), native_endian);
    }
}

test "counting and fixed writers produce the same final length" {
    var counting = CountingWriter.init();
    encodeExamplePacket(&counting);

    var buf: [32]u8 = undefined;
    var fixed = FixedBufferWriter.init(&buf);
    encodeExamplePacket(&fixed);

    const int_bytes: [2]u8 = switch (native_endian) {
        .little => .{ 0x22, 0x11 },
        .big => .{ 0x11, 0x22 },
    };

    try std.testing.expectEqual(@as(usize, 9), counting.seek);
    try std.testing.expectEqual(counting.seek, fixed.seek);
    try std.testing.expectEqualSlices(u8, &.{
        0xaa,
        int_bytes[0], int_bytes[1],
        0x00,
        'z', 'i', 'g',
        0xff, 0xff,
    }, fixed.buf[0..fixed.seek]);
}

test "consumer code can compute padding from seek" {
    var counting = CountingWriter.init();
    counting.writeByte(1);
    counting.splatByte(0, (8 - (counting.seek % 8)) % 8);
    counting.writeByte(2);
    try std.testing.expectEqual(@as(usize, 9), counting.seek);

    var buf: [16]u8 = undefined;
    var fixed = FixedBufferWriter.init(&buf);
    fixed.writeByte(1);
    fixed.splatByte(0, (8 - (fixed.seek % 8)) % 8);
    fixed.writeByte(2);

    try std.testing.expectEqual(counting.seek, fixed.seek);
    try std.testing.expectEqualSlices(u8, &.{ 1, 0, 0, 0, 0, 0, 0, 0, 2 }, fixed.buf[0..fixed.seek]);
}

test "fixed writer can patch request header after encoding" {
    const payload = "hello";

    var counting = CountingWriter.init();
    encodeRequest(&counting, payload);

    const buf = try std.testing.allocator.alloc(u8, counting.seek);
    defer std.testing.allocator.free(buf);

    var fixed = FixedBufferWriter.init(buf);
    encodeRequest(&fixed, payload);

    try std.testing.expectEqual(counting.seek, fixed.seek);
    try std.testing.expectEqual(@as(u8, 99), fixed.buf[0]);
    try std.testing.expectEqual(@as(u8, 7), fixed.buf[1]);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, fixed.buf[2..4], native_endian));
    try std.testing.expectEqualSlices(u8, payload, fixed.buf[4..9]);
    try std.testing.expectEqualSlices(u8, &.{ 0, 0, 0 }, fixed.buf[9..12]);
}
