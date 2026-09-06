import struct, sys

PALETTE_TXT = """0;00FFFF
1;7c8090
2;30384c
3;a8a4ac
4;0
5;fc5454
6;e8fc60
7;a80000
8;587088
9;f0f0f0
10;707080
11;7898a0
12;606060
13;0
14;d00000
15;fcfcfc
16;0
17;282828
18;505050
19;7c7c7c
20;a4a4a4
21;d0d0d0
22;f8f8f8
23;280000
24;282800
25;2800
26;2828
27;28
28;280028
29;502828
30;505028
31;285028
32;285050
33;282850
34;502850
35;7c5050
36;7c7c50
37;507c50
38;507c7c
39;50507c
40;7c507c
41;a47c7c
42;a4a47c
43;7ca47c
44;7ca4a4
45;7c7ca4
46;a47ca4
47;d0a4a4
48;d0d0a4
49;a4d0a4
50;a4d0d0
51;a4a4d0
52;d0a4d0
53;f8d0d0
54;f8f8d0
55;d0f8d0
56;d0f8f8
57;d0d0f8
58;f8d0f8
59;500000
60;502800
61;505000
62;285000
63;5000
64;5028
65;5050
66;2850
67;50
68;280050
69;500050
70;500028
71;7c2828
72;7c5028
73;7c7c28
74;507c28
75;287c28
76;287c50
77;287c7c
78;28507c
79;28287c
80;50287c
81;7c287c
82;7c2850
83;a45050
84;a47c50
85;a4a450
86;7ca450
87;50a450
88;50a47c
89;50a4a4
90;507ca4
91;5050a4
92;7c50a4
93;a450a4
94;a4507c
95;d07c7c
96;d0a47c
97;d0d07c
98;a4d07c
99;7cd07c
100;7cd0a4
101;7cd0d0
102;7ca4d0
103;7c7cd0
104;a47cd0
105;d07cd0
106;d07ca4
107;f8a4a4
108;f8d0a4
109;f8f8a4
110;d0f8a4
111;a4f8a4
112;a4f8d0
113;a4f8f8
114;a4d0f8
115;a4a4f8
116;d0a4f8
117;f8a4f8
118;f8a4d0
119;7c0000
120;7c3000
121;7c6400
122;647c00
123;307c00
124;7c00
125;7c30
126;7c64
127;647c
128;307c
129;7c
130;30007c
131;64007c
132;7c0064
133;7c0030
134;a42828
135;a45c28
136;a48c28
137;8ca428
138;5ca428
139;28a428
140;28a45c
141;28a48c
142;288ca4
143;285ca4
144;2828a4
145;5c28a4
146;8c28a4
147;a4288c
148;a4285c
149;d05454
150;d08454
151;d0b854
152;b8d054
153;84d054
154;54d054
155;54d084
156;54d0b8
157;54b8d0
158;5484d0
159;5454d0
160;8454d0
161;b854d0
162;d054b8
163;d05484
164;f87c7c
165;f8b07c
166;f8e07c
167;e0f87c
168;b0f87c
169;7cf87c
170;7cf8b0
171;7cf8e0
172;7ce0f8
173;7cb0f8
174;7c7cf8
175;b07cf8
176;e07cf8
177;f87ce0
178;f87cb0
179;a40000
180;a44000
181;a48400
182;84a400
183;40a400
184;a400
185;a440
186;a484
187;84a4
188;40a4
189;a4
190;4000a4
191;8400a4
192;a40084
193;a40040
194;d02828
195;d06c28
196;d0b028
197;b0d028
198;6cd028
199;28d028
200;28d06c
201;28d0b0
202;28b0d0
203;286cd0
204;2828d0
205;6c28d0
206;b028d0
207;d028b0
208;d0286c
209;f85454
210;f89454
211;f8d854
212;d8f854
213;94f854
214;54f854
215;54f894
216;54f8d8
217;54d8f8
218;5494f8
219;5454f8
220;9454f8
221;d854f8
222;f854d8
223;f85494
224;d00000
225;d04c00
226;d09c00
227;b4d000
228;68d000
229;18d000
230;d034
231;d080
232;d0d0
233;80d0
234;34d0
235;1800d0
236;6800d0
237;b400d0
238;d0009c
239;d0004c
240;f82828
241;f87828
242;f8c428
243;e0f828
244;90f828
245;44f828
246;28f85c
247;28f8ac
248;28f8f8
249;28acf8
250;285cf8
251;4428f8
252;9028f8
253;e028f8
254;f828c4
255;f82878"""

def load_palette():
    pal = {}
    for line in PALETTE_TXT.strip().split("\n"):
        idx, hexval = line.split(";")
        hexval = hexval.rjust(6, "0")
        r = int(hexval[0:2], 16)
        g = int(hexval[2:4], 16)
        b = int(hexval[4:6], 16)
        pal[int(idx)] = (r, g, b)
    return pal

PALETTE = load_palette()

def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def s16(b, o): return struct.unpack_from("<h", b, o)[0]

def parse_header(data):
    magic = data[0:8]
    name = data[0x0A:0x12].split(b"\x00")[0].decode("ascii", errors="replace")
    total_len = u32(data, 0x20)
    detailed_off = u32(data, 0x8B)
    icon_off = u32(data, 0x8F)
    anim_off = u32(data, 0x93)
    return dict(name=name, total_len=total_len, detailed_off=detailed_off,
                icon_off=icon_off, anim_off=anim_off, file_len=len(data))

def parse_frame(data, off):
    frame_len = u32(data, off+0)
    frame_num = u32(data, off+4)
    prev = u32(data, off+8)
    nxt = u32(data, off+12)
    unk1 = u32(data, off+16)
    unk2 = u16(data, off+20)
    xoff = s16(data, off+22)
    yoff = s16(data, off+24)
    width = u16(data, off+26)
    height = u16(data, off+28)
    return dict(off=off, frame_len=frame_len, frame_num=frame_num, prev=prev, nxt=nxt,
                xoff=xoff, yoff=yoff, width=width, height=height)

def render_frame(data, frame):
    off = frame["off"]
    width, height = frame["width"], frame["height"]
    pixdata_start = off + 30
    # frame_len always undercounts a frame's real pixel data by a fixed 16 bytes (confirmed: every
    # frame in every fish tested has its "nxt" pointer sitting exactly 16 bytes past off+frame_len,
    # and those 16 bytes decode as genuine additional drawing commands, not padding). Prefer the
    # frame's own "nxt" pointer -- an independent, reliable value -- as the true end of its pixel
    # data; only fall back to frame_len+16 for the last frame in a chain, where nxt is 0.
    pixdata_end = frame["nxt"] if frame.get("nxt") else off + frame["frame_len"] + 16
    buf = bytearray(width*height)  # 0 = transparent marker handled separately
    alpha = bytearray(width*height)
    pos = pixdata_start
    # The pixel stream is always already "positioned" on row 0 when it starts -- a run with a
    # negative (continue-current-line) position code is valid as the very first event, and refers
    # to row 0, not to "no row yet". Starting this at -1 was an off-by-one: it silently discarded
    # every frame's first drawing command(s) whenever a frame's very first row was itself made up
    # of continue-line runs (extremely common -- it's a thin sliver right at the top/tip of
    # whatever's drawn), losing a real row of pixels from every affected frame.
    cur_line = 0
    line_x = 0
    while pos < pixdata_end - 3:
        dlen = u16(data, pos)
        posval = s16(data, pos+2)
        pos += 4
        if dlen == 0 and posval == 0:
            # possible end marker; try to move to next line
            cur_line += 1
            line_x = 0
            if cur_line >= height:
                break
            continue
        if posval >= 0:
            cur_line += 1
            line_x = posval
        else:
            line_x = -posval
        if cur_line < 0 or cur_line >= height:
            pos += dlen
            continue
        pixels = data[pos:pos+dlen]
        pos += dlen
        for i, px in enumerate(pixels):
            x = line_x + i
            if 0 <= x < width:
                buf[cur_line*width + x] = px
                alpha[cur_line*width + x] = 255
    return buf, alpha

if __name__ == "__main__":
    path = sys.argv[1]
    data = open(path, "rb").read()
    hdr = parse_header(data)
    print("Header:", hdr)
    frame = parse_frame(data, hdr["detailed_off"])
    print("Detailed frame header:", frame)
