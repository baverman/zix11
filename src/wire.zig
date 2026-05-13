const std = @import("std");

pub fn pad4(len: usize) usize {
    return (4 - (len & 3)) & 3;
}

pub fn structListByteLen(list: anytype) usize {
    var total: usize = 0;
    for (list) |elem| total += elem.byteLen();
    return total;
}

pub fn computeValueMask(comptime Spec: type, values: anytype) u32 {
    var mask: u32 = 0;
    inline for (Spec.fields) |field| {
        if (@field(values, field.name) != null) {
            mask |= field.bit;
        }
    }
    return mask;
}

pub fn valueListByteLen(comptime Spec: type, values: anytype) usize {
    var total: usize = 0;
    inline for (Spec.fields) |field| {
        if (@field(values, field.name) != null) {
            total += maskedValueByteLen(field.value_type);
        }
    }
    return total;
}

pub fn writeValueList(comptime Spec: type, values: anytype, writer: *std.Io.Writer) std.Io.Writer.Error!void {
    inline for (Spec.fields) |field| {
        if (@field(values, field.name)) |value| {
            try writeMaskedValue(field.value_type, writer, value);
        }
    }
}

pub fn maskOf(comptime E: type, flags: []const E) u32 {
    var mask: u32 = 0;
    for (flags) |flag| mask |= @intFromEnum(flag);
    return mask;
}

fn maskedValueByteLen(comptime T: type) usize {
    return switch (@typeInfo(T)) {
        .@"enum" => @sizeOf(@typeInfo(T).@"enum".tag_type),
        else => @sizeOf(T),
    };
}

fn writeMaskedValue(comptime T: type, writer: *std.Io.Writer, value: T) std.Io.Writer.Error!void {
    switch (@typeInfo(T)) {
        .@"enum" => |info| try writer.writeInt(info.tag_type, @intFromEnum(value), .little),
        .int => |info| {
            if (info.bits == 8) {
                try writer.writeByte(value);
            } else {
                try writer.writeInt(T, value, .little);
            }
        },
        else => @compileError("unsupported masked value type"),
    }
}

test "pad4" {
    try std.testing.expectEqual(@as(usize, 0), pad4(0));
    try std.testing.expectEqual(@as(usize, 3), pad4(1));
    try std.testing.expectEqual(@as(usize, 2), pad4(2));
    try std.testing.expectEqual(@as(usize, 1), pad4(3));
    try std.testing.expectEqual(@as(usize, 0), pad4(4));
}
