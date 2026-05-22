const std = @import("std");
const zix11 = @import("zix11");

const x = zix11.x;
const xkb = zix11.ext.xkb;

const core_kbd: u16 = @intCast(@intFromEnum(xkb.ID.UseCoreKbd));
const selected_events: u16 = @intCast(xkb.EventType.of(&.{
    .NewKeyboardNotify,
    .MapNotify,
    .StateNotify,
    .NamesNotify,
}));
const selected_map_parts: u16 = @intCast(xkb.MapPart.of(&.{
    .KeyTypes,
    .KeySyms,
    .ModifierMap,
    .ExplicitComponents,
    .KeyActions,
    .KeyBehaviors,
    .VirtualMods,
    .VirtualModMap,
}));
const selected_state_parts: u16 = @intCast(xkb.StatePart.of(&.{
    .GroupState,
    .GroupBase,
    .GroupLatch,
    .GroupLock,
}));
const selected_name_details: u16 = @intCast(xkb.NameDetail.of(&.{.GroupNames}));
const selected_new_keyboard_details: u16 = @intCast(xkb.NKNDetail.of(&.{
    .Keycodes,
    .Geometry,
    .DeviceID,
}));

fn atomName(conn: *zix11.Connection, atom: x.Atom, buffer: []u8) ![]const u8 {
    const reply = try conn.requestBuf(buffer, x.GetAtomName, .{ .atom = atom });
    return reply.name;
}

fn groupIndex(group: xkb.Group) usize {
    return @intFromEnum(group);
}

fn groupAtom(reply: *const xkb.GetNamesReply, group: xkb.Group) ?x.Atom {
    const groups = reply.valueList.GroupNames orelse return null;
    const idx = groupIndex(group);
    const bit: u8 = @as(u8, 1) << @intCast(idx);
    if ((reply.groupNames & bit) == 0) return null;

    var slice_idx: usize = 0;
    var bit_idx: usize = 0;
    while (bit_idx < idx) : (bit_idx += 1) {
        const prev_bit: u8 = @as(u8, 1) << @intCast(bit_idx);
        if ((reply.groupNames & prev_bit) != 0) slice_idx += 1;
    }
    if (slice_idx >= groups.groups.len) return null;
    return groups.groups[slice_idx];
}

fn printCurrentLayout(conn: *zix11.Connection, allocator: std.mem.Allocator, reason: []const u8) !void {
    var names = try conn.requestAlloc(allocator, xkb.GetNames, .{
        .deviceSpec = core_kbd,
        .which = xkb.NameDetail.of(&.{.GroupNames}),
    });
    defer names.deinit(allocator);

    const state = try conn.request(xkb.GetState, .{
        .deviceSpec = core_kbd,
    });
    const idx = groupIndex(state.group);

    if (groupAtom(&names, state.group)) |atom| {
        var name_buf: [256]u8 = undefined;
        const name = atomName(conn, atom, name_buf[0..]) catch |err| {
            std.debug.print("{s}: group={} atom=0x{x} name lookup failed: {any}\n", .{
                reason,
                idx + 1,
                @intFromEnum(atom),
                err,
            });
            return;
        };
        std.debug.print("{s}: group={} layout={s}\n", .{ reason, idx + 1, name });
    } else {
        std.debug.print("{s}: group={} layout=<unnamed>\n", .{ reason, idx + 1 });
    }
}

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.XKEYBOARD);
    const version = try conn.request(xkb.UseExtension, .{
        .wantedMajor = 1,
        .wantedMinor = 0,
    });
    if (!version.supported) {
        std.debug.print("XKB extension not supported by the server\n", .{});
        return;
    }

    try conn.request(xkb.SelectEvents, .{
        .deviceSpec = core_kbd,
        .affectWhich = selected_events,
        .clear = 0,
        .selectAll = 0,
        .affectMap = selected_map_parts,
        .map = selected_map_parts,
        .details = .{
            .NewKeyboardNotify = .{
                .affectNewKeyboard = selected_new_keyboard_details,
                .newKeyboardDetails = selected_new_keyboard_details,
            },
            .StateNotify = .{
                .affectState = selected_state_parts,
                .stateDetails = selected_state_parts,
            },
            .NamesNotify = .{
                .affectNames = selected_name_details,
                .namesDetails = selected_name_details,
            },
        },
    });

    std.debug.print("XKB server version {}.{}; listening for keyboard layout changes\n", .{
        version.serverMajor,
        version.serverMinor,
    });
    try printCurrentLayout(&conn, init.gpa, "initial");

    while (true) {
        switch (try conn.nextEvent()) {
            .XKbStateNotify => |ev| {
                std.debug.print("XKB StateNotify: group={} changed=0x{x}\n", .{
                    groupIndex(ev.group) + 1,
                    ev.changed,
                });
                try printCurrentLayout(&conn, init.gpa, "state");
            },
            .XKbNamesNotify => |ev| {
                std.debug.print("XKB NamesNotify: changed=0x{x} changed_group_names=0x{x}\n", .{
                    ev.changed,
                    ev.changedGroupNames,
                });
                try printCurrentLayout(&conn, init.gpa, "names");
            },
            .XKbMapNotify => |ev| {
                std.debug.print("XKB MapNotify: changed=0x{x} virtual_mods=0x{x}\n", .{
                    ev.changed,
                    ev.virtualMods,
                });
                try printCurrentLayout(&conn, init.gpa, "map");
            },
            .XKbNewKeyboardNotify => |ev| {
                std.debug.print("XKB NewKeyboardNotify: device={} changed=0x{x}\n", .{
                    ev.deviceID,
                    ev.changed,
                });
                try printCurrentLayout(&conn, init.gpa, "new keyboard");
            },
            else => {},
        }
    }
}
