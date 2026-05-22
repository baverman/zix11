const std = @import("std");

pub fn pad(len: usize, alignment: comptime_int) usize {
    comptime std.debug.assert(alignment != 0);
    comptime std.debug.assert((alignment & (alignment - 1)) == 0);
    const mask: comptime_int = alignment - 1;
    return (alignment - (len & mask)) & mask;
}

pub fn pad4(len: usize) usize {
    return pad(len, 4);
}

pub fn requiredPad(offset: usize, alignment: usize, start_offset: usize) usize {
    std.debug.assert(alignment != 0);
    const offset_mod = offset % alignment;
    const start_mod = start_offset % alignment;
    return (start_mod + alignment - offset_mod) % alignment;
}

pub fn computeValueMask(comptime Spec: type, values: anytype) Spec.mask_type {
    var mask: Spec.mask_type = 0;
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

pub fn writeValueList(comptime Spec: type, values: anytype, writer: anytype) void {
    inline for (Spec.fields) |field| {
        if (@field(values, field.name)) |value| {
            writeMaskedValue(field.value_type, writer, value);
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

fn writeMaskedValue(comptime T: type, writer: anytype, value: T) void {
    switch (@typeInfo(T)) {
        .@"enum" => |info| writer.writeInt(info.tag_type, @intFromEnum(value)),
        .int => |info| {
            if (info.bits == 8) {
                writer.writeByte(value);
            } else {
                writer.writeInt(T, value);
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

test "pad" {
    try std.testing.expectEqual(@as(usize, 0), pad(0, 4));
    try std.testing.expectEqual(@as(usize, 3), pad(1, 4));
    try std.testing.expectEqual(@as(usize, 2), pad(2, 4));
    try std.testing.expectEqual(@as(usize, 1), pad(3, 4));
    try std.testing.expectEqual(@as(usize, 0), pad(4, 4));
    try std.testing.expectEqual(@as(usize, 1), pad(3, 2));
    try std.testing.expectEqual(@as(usize, 5), pad(3, 8));
}

test "requiredPad" {
    try std.testing.expectEqual(@as(usize, 0), requiredPad(2, 4, 2));
    try std.testing.expectEqual(@as(usize, 2), requiredPad(0, 4, 2));
    try std.testing.expectEqual(@as(usize, 3), requiredPad(3, 4, 2));
    try std.testing.expectEqual(@as(usize, 0), requiredPad(6, 4, 2));
}
