const std = @import("std");

pub const Error = std.Io.Reader.Error || std.Io.Writer.Error || error{
    BufferTooSmall,
    MalformedPacket,
    UnexpectedReplyType,
    UnsupportedFormat,
};

pub fn pad4(len: usize) usize {
    return (4 - (len & 3)) & 3;
}

pub fn valueByteLen(format: u8, units: u32) Error!usize {
    const unit_bytes: usize = switch (format) {
        0 => 0,
        8 => 1,
        16 => 2,
        32 => 4,
        else => return error.UnsupportedFormat,
    };
    return unit_bytes * units;
}

pub fn StructView(comptime T: type) type {
    return struct {
        bytes: []const u8,
        count: usize,

        pub fn iterator(self: @This()) StructIterator(T) {
            return .init(self.bytes, self.count);
        }
    };
}

pub fn StructIterator(comptime T: type) type {
    return struct {
        reader: std.Io.Reader,
        remaining: usize,

        pub fn init(bytes: []const u8, count: usize) @This() {
            return .{
                .reader = .fixed(bytes),
                .remaining = count,
            };
        }

        pub fn next(self: *@This()) Error!?T {
            if (self.remaining == 0) return null;
            self.remaining -= 1;
            return try T.decode(&self.reader);
        }
    };
}

pub fn take_struct_view(comptime T: type, reader: *std.Io.Reader, count: usize) Error!StructView(T) {
    const start = reader.seek;
    var remaining = count;
    while (remaining > 0) : (remaining -= 1) {
        _ = try T.decode(reader);
    }
    const end = reader.seek;
    return .{
        .bytes = reader.buffer[start..end],
        .count = count,
    };
}

test "pad4" {
    try std.testing.expectEqual(@as(usize, 0), pad4(0));
    try std.testing.expectEqual(@as(usize, 3), pad4(1));
    try std.testing.expectEqual(@as(usize, 2), pad4(2));
    try std.testing.expectEqual(@as(usize, 1), pad4(3));
    try std.testing.expectEqual(@as(usize, 0), pad4(4));
}
