pub const Extension = enum {
    RENDER,
};

pub const ExtensionInfo = struct {
    major_opcode: u8,
    first_event: u8,
    first_error: u8,
};

pub fn xname(ext: Extension) []const u8 {
    return switch (ext) {
        .RENDER => "RENDER",
    };
}
