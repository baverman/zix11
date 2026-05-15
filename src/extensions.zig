pub const Extension = enum {
    RENDER,
    MIT_SHM,
};

pub const ExtensionInfo = struct {
    major_opcode: u8,
    first_event: u8,
    first_error: u8,
};

pub fn xname(ext: Extension) []const u8 {
    return switch (ext) {
        .RENDER => "RENDER",
        .MIT_SHM => "MIT-SHM",
    };
}
