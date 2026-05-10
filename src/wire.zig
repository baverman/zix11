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

test "pad4" {
    try std.testing.expectEqual(@as(usize, 0), pad4(0));
    try std.testing.expectEqual(@as(usize, 3), pad4(1));
    try std.testing.expectEqual(@as(usize, 2), pad4(2));
    try std.testing.expectEqual(@as(usize, 1), pad4(3));
    try std.testing.expectEqual(@as(usize, 0), pad4(4));
}
