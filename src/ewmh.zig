const std = @import("std");

pub const SizeHints = union(enum) {
    PPosition: struct { u32, u32 },
    PMinSize: struct { u32, u32 },
    PMaxSize: struct { u32, u32 },

    pub fn encode(hints: []const @This()) [18]u32 {
        var result = std.mem.zeroes([18]u32);
        var flag: u32 = 0;
        for (hints) |it| {
            switch (it) {
                .PPosition => |h| {
                    flag |= 4;
                    result[1] = h[0];
                    result[2] = h[1];
                },
                .PMinSize => |h| {
                    flag |= 16;
                    result[5] = h[0];
                    result[6] = h[1];
                },
                .PMaxSize => |h| {
                    flag |= 32;
                    result[7] = h[0];
                    result[8] = h[1];
                },
            }
        }
        result[0] = flag;
        return result;
    }
};

test "SizeHints" {
    const sh = SizeHints.encode(&.{
        .{ .PMinSize = .{ 10, 20 } },
        .{ .PMaxSize = .{ 30, 40 } },
    });
    try std.testing.expectEqualSlices(u32, &.{ 48, 0, 0, 0, 0, 10, 20, 30, 40 }, sh[0..9]);
}
