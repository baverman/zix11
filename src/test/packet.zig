const std = @import("std");

pub fn makePacket(buf: []u8, data: anytype) []const u8 {
    comptime var pos = 0;
    inline for (data) |it| {
        const T = std.meta.Elem(@TypeOf(it));
        const s = std.mem.sliceAsBytes(it);
        @memcpy(buf[pos..][0..s.len], s);
        pos += it.len * @sizeOf(T);
    }
    return buf[0..pos];
}
