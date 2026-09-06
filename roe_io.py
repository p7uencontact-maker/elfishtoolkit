"""Reading and writing .ROE files.

Unlike .FSH, a .ROE is just a flat byte blob -- there's no header/offset table to parse, every
"gene" is a single byte sitting at a fixed address. So this module is deliberately tiny: load the
bytes, poke individual offsets, save them back out.
"""

ROE_SIZE = 1548  # 0x000 - 0x60B inclusive -- the standard size of an El-Fish .ROE save file


class RoeFile:
    def __init__(self, data, path=None):
        self.data = bytearray(data)
        self.path = path

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            data = f.read()
        return cls(data, path=path)

    def get(self, offset):
        return self.data[offset]

    def set(self, offset, value):
        if not (0 <= value <= 255):
            raise ValueError(f"byte value {value} out of range 0-255")
        if offset >= len(self.data):
            raise ValueError(f"offset 0x{offset:03X} is past the end of this file "
                              f"({len(self.data)} bytes)")
        self.data[offset] = value

    def clone(self):
        return RoeFile(bytes(self.data), path=self.path)

    def save_as(self, path):
        with open(path, "wb") as f:
            f.write(self.data)
        self.path = path

    @property
    def size_warning(self):
        """None if this file is the expected size; otherwise a human-readable heads-up."""
        if len(self.data) == ROE_SIZE:
            return None
        return (f"This file is {len(self.data)} bytes, not the usual {ROE_SIZE} -- it may not be "
                f"a standard El-Fish .ROE, or offsets past the end of it can't be edited.")
