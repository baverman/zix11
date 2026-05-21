const std = @import("std");

pub const errors = @import("errors.zig");
pub const io = @import("io.zig");
pub const x = @import("gen/xproto.zig");
pub const ext = @import("ext.zig");
pub const ewmh = @import("ewmh.zig");
pub const connection = @import("connection.zig");
pub const protocol = @import("protocol.zig");
pub const properties = @import("properties.zig");
pub const atoms = @import("atoms.zig");
pub const events = @import("events.zig");

pub const Connection = connection.Connection;
pub const Event = events.Event;
