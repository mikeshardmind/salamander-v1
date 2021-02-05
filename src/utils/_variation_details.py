#   Copyright 2020-present Michael Hall
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

# -------------------------------------------------------------------------------
# This file last updated at: 2020-11-06 for Unicode Version 13.1
# based on the guidleines published by The Unicode Consortium (link below)
# https://www.unicode.org/Public/13.0.0/ucd/emoji/emoji-variation-sequences.txt
# See: http://www.unicode.org/reports/tr51/#emoji_data
# for The Unicode Consortium's current guidelines for emojis
# -------------------------------------------------------------------------------
# This excludes emojis with a default Emoji_Presentation=yes
# See: https://github.com/twitter/twemoji/issues/363
# -------------------------------------------------------------------------------

#: Version without handling for twemoji kept for reference
_VALID_VARIATION_16_CHARS = (
    "\u0023",
    "\u002A",
    "\u0030",
    "\u0031",
    "\u0032",
    "\u0033",
    "\u0034",
    "\u0035",
    "\u0036",
    "\u0037",
    "\u0038",
    "\u0039",
    "\u00A9",
    "\u00AE",
    "\u203C",
    "\u2049",
    "\u2122",
    "\u2139",
    "\u2194",
    "\u2195",
    "\u2196",
    "\u2197",
    "\u2198",
    "\u2199",
    "\u21A9",
    "\u21AA",
    "\u231A",
    "\u231B",
    "\u2328",
    "\u23CF",
    "\u23E9",
    "\u23EA",
    "\u23ED",
    "\u23EE",
    "\u23EF",
    "\u23F1",
    "\u23F2",
    "\u23F3",
    "\u23F8",
    "\u23F9",
    "\u23FA",
    "\u24C2",
    "\u25AA",
    "\u25AB",
    "\u25B6",
    "\u25C0",
    "\u25FB",
    "\u25FC",
    "\u25FD",
    "\u25FE",
    "\u2600",
    "\u2601",
    "\u2602",
    "\u2603",
    "\u2604",
    "\u260E",
    "\u2611",
    "\u2614",
    "\u2615",
    "\u2618",
    "\u261D",
    "\u2620",
    "\u2622",
    "\u2623",
    "\u2626",
    "\u262A",
    "\u262E",
    "\u262F",
    "\u2638",
    "\u2639",
    "\u263A",
    "\u2640",
    "\u2642",
    "\u2648",
    "\u2649",
    "\u264A",
    "\u264B",
    "\u264C",
    "\u264D",
    "\u264E",
    "\u264F",
    "\u2650",
    "\u2651",
    "\u2652",
    "\u2653",
    "\u265F",
    "\u2660",
    "\u2663",
    "\u2665",
    "\u2666",
    "\u2668",
    "\u267B",
    "\u267E",
    "\u267F",
    "\u2692",
    "\u2693",
    "\u2694",
    "\u2695",
    "\u2696",
    "\u2697",
    "\u2699",
    "\u269B",
    "\u269C",
    "\u26A0",
    "\u26A1",
    "\u26A7",
    "\u26AA",
    "\u26AB",
    "\u26B0",
    "\u26B1",
    "\u26BD",
    "\u26BE",
    "\u26C4",
    "\u26C5",
    "\u26C8",
    "\u26CF",
    "\u26D1",
    "\u26D3",
    "\u26D4",
    "\u26E9",
    "\u26EA",
    "\u26F0",
    "\u26F1",
    "\u26F2",
    "\u26F3",
    "\u26F4",
    "\u26F5",
    "\u26F7",
    "\u26F8",
    "\u26F9",
    "\u26FA",
    "\u26FD",
    "\u2702",
    "\u2708",
    "\u2709",
    "\u270C",
    "\u270D",
    "\u270F",
    "\u2712",
    "\u2714",
    "\u2716",
    "\u271D",
    "\u2721",
    "\u2733",
    "\u2734",
    "\u2744",
    "\u2747",
    "\u2753",
    "\u2757",
    "\u2763",
    "\u2764",
    "\u27A1",
    "\u2934",
    "\u2935",
    "\u2B05",
    "\u2B06",
    "\u2B07",
    "\u2B1B",
    "\u2B1C",
    "\u2B50",
    "\u2B55",
    "\u3030",
    "\u303D",
    "\u3297",
    "\u3299",
    "\U0001F004",
    "\U0001F170",
    "\U0001F171",
    "\U0001F17E",
    "\U0001F17F",
    "\U0001F202",
    "\U0001F21A",
    "\U0001F22F",
    "\U0001F237",
    "\U0001F30D",
    "\U0001F30E",
    "\U0001F30F",
    "\U0001F315",
    "\U0001F31C",
    "\U0001F321",
    "\U0001F324",
    "\U0001F325",
    "\U0001F326",
    "\U0001F327",
    "\U0001F328",
    "\U0001F329",
    "\U0001F32A",
    "\U0001F32B",
    "\U0001F32C",
    "\U0001F336",
    "\U0001F378",
    "\U0001F37D",
    "\U0001F393",
    "\U0001F396",
    "\U0001F397",
    "\U0001F399",
    "\U0001F39A",
    "\U0001F39B",
    "\U0001F39E",
    "\U0001F39F",
    "\U0001F3A7",
    "\U0001F3AC",
    "\U0001F3AD",
    "\U0001F3AE",
    "\U0001F3C2",
    "\U0001F3C4",
    "\U0001F3C6",
    "\U0001F3CA",
    "\U0001F3CB",
    "\U0001F3CC",
    "\U0001F3CD",
    "\U0001F3CE",
    "\U0001F3D4",
    "\U0001F3D5",
    "\U0001F3D6",
    "\U0001F3D7",
    "\U0001F3D8",
    "\U0001F3D9",
    "\U0001F3DA",
    "\U0001F3DB",
    "\U0001F3DC",
    "\U0001F3DD",
    "\U0001F3DE",
    "\U0001F3DF",
    "\U0001F3E0",
    "\U0001F3ED",
    "\U0001F3F3",
    "\U0001F3F5",
    "\U0001F3F7",
    "\U0001F408",
    "\U0001F415",
    "\U0001F41F",
    "\U0001F426",
    "\U0001F43F",
    "\U0001F441",
    "\U0001F442",
    "\U0001F446",
    "\U0001F447",
    "\U0001F448",
    "\U0001F449",
    "\U0001F44D",
    "\U0001F44E",
    "\U0001F453",
    "\U0001F46A",
    "\U0001F47D",
    "\U0001F4A3",
    "\U0001F4B0",
    "\U0001F4B3",
    "\U0001F4BB",
    "\U0001F4BF",
    "\U0001F4CB",
    "\U0001F4DA",
    "\U0001F4DF",
    "\U0001F4E4",
    "\U0001F4E5",
    "\U0001F4E6",
    "\U0001F4EA",
    "\U0001F4EB",
    "\U0001F4EC",
    "\U0001F4ED",
    "\U0001F4F7",
    "\U0001F4F9",
    "\U0001F4FA",
    "\U0001F4FB",
    "\U0001F4FD",
    "\U0001F508",
    "\U0001F50D",
    "\U0001F512",
    "\U0001F513",
    "\U0001F549",
    "\U0001F54A",
    "\U0001F550",
    "\U0001F551",
    "\U0001F552",
    "\U0001F553",
    "\U0001F554",
    "\U0001F555",
    "\U0001F556",
    "\U0001F557",
    "\U0001F558",
    "\U0001F559",
    "\U0001F55A",
    "\U0001F55B",
    "\U0001F55C",
    "\U0001F55D",
    "\U0001F55E",
    "\U0001F55F",
    "\U0001F560",
    "\U0001F561",
    "\U0001F562",
    "\U0001F563",
    "\U0001F564",
    "\U0001F565",
    "\U0001F566",
    "\U0001F567",
    "\U0001F56F",
    "\U0001F570",
    "\U0001F573",
    "\U0001F574",
    "\U0001F575",
    "\U0001F576",
    "\U0001F577",
    "\U0001F578",
    "\U0001F579",
    "\U0001F587",
    "\U0001F58A",
    "\U0001F58B",
    "\U0001F58C",
    "\U0001F58D",
    "\U0001F590",
    "\U0001F5A5",
    "\U0001F5A8",
    "\U0001F5B1",
    "\U0001F5B2",
    "\U0001F5BC",
    "\U0001F5C2",
    "\U0001F5C3",
    "\U0001F5C4",
    "\U0001F5D1",
    "\U0001F5D2",
    "\U0001F5D3",
    "\U0001F5DC",
    "\U0001F5DD",
    "\U0001F5DE",
    "\U0001F5E1",
    "\U0001F5E3",
    "\U0001F5E8",
    "\U0001F5EF",
    "\U0001F5F3",
    "\U0001F5FA",
    "\U0001F610",
    "\U0001F687",
    "\U0001F68D",
    "\U0001F691",
    "\U0001F694",
    "\U0001F698",
    "\U0001F6AD",
    "\U0001F6B2",
    "\U0001F6B9",
    "\U0001F6BA",
    "\U0001F6BC",
    "\U0001F6CB",
    "\U0001F6CD",
    "\U0001F6CE",
    "\U0001F6CF",
    "\U0001F6E0",
    "\U0001F6E1",
    "\U0001F6E2",
    "\U0001F6E3",
    "\U0001F6E4",
    "\U0001F6E5",
    "\U0001F6E9",
    "\U0001F6F0",
    "\U0001F6F3",
)

CHARS_REQUIRING_VARIATION = (
    # "\U00000023",  # twemoji exclusion
    # "\U0000002a",  # twemoji exclusion
    # "\U00000030",  # twemoji exclusion
    # "\U00000031",  # twemoji exclusion
    # "\U00000032",  # twemoji exclusion
    # "\U00000033",  # twemoji exclusion
    # "\U00000034",  # twemoji exclusion
    # "\U00000035",  # twemoji exclusion
    # "\U00000036",  # twemoji exclusion
    # "\U00000037",  # twemoji exclusion
    # "\U00000038",  # twemoji exclusion
    # "\U00000039",  # twemoji exclusion
    "\U000000a9",
    "\U000000ae",
    "\U0000203c",
    "\U00002049",
    "\U00002122",
    "\U00002139",
    "\U00002194",
    "\U00002195",
    "\U00002196",
    "\U00002197",
    "\U00002198",
    "\U00002199",
    "\U000021a9",
    "\U000021aa",
    # "\U0000231a",  # twemoji exclusion
    # "\U0000231b",  # twemoji exclusion
    "\U00002328",
    "\U000023cf",
    # "\U000023e9",  # twemoji exclusion
    # "\U000023ea",  # twemoji exclusion
    "\U000023ed",
    "\U000023ee",
    "\U000023ef",
    "\U000023f1",
    "\U000023f2",
    # "\U000023f3",  # twemoji exclusion
    "\U000023f8",
    "\U000023f9",
    "\U000023fa",
    "\U000024c2",
    "\U000025aa",
    "\U000025ab",
    "\U000025b6",
    "\U000025c0",
    "\U000025fb",
    "\U000025fc",
    # "\U000025fd",  # twemoji exclusion
    # "\U000025fe",  # twemoji exclusion
    "\U00002600",
    "\U00002601",
    "\U00002602",
    "\U00002603",
    "\U00002604",
    "\U0000260e",
    "\U00002611",
    # "\U00002614",  # twemoji exclusion
    # "\U00002615",  # twemoji exclusion
    "\U00002618",
    "\U0000261d",
    "\U00002620",
    "\U00002622",
    "\U00002623",
    "\U00002626",
    "\U0000262a",
    "\U0000262e",
    "\U0000262f",
    "\U00002638",
    "\U00002639",
    "\U0000263a",
    "\U00002640",
    "\U00002642",
    # "\U00002648",  # twemoji exclusion
    # "\U00002649",  # twemoji exclusion
    # "\U0000264a",  # twemoji exclusion
    # "\U0000264b",  # twemoji exclusion
    # "\U0000264c",  # twemoji exclusion
    # "\U0000264d",  # twemoji exclusion
    # "\U0000264e",  # twemoji exclusion
    # "\U0000264f",  # twemoji exclusion
    # "\U00002650",  # twemoji exclusion
    # "\U00002651",  # twemoji exclusion
    # "\U00002652",  # twemoji exclusion
    # "\U00002653",  # twemoji exclusion
    "\U0000265f",
    "\U00002660",
    "\U00002663",
    "\U00002665",
    "\U00002666",
    "\U00002668",
    "\U0000267b",
    "\U0000267e",
    # "\U0000267f",  # twemoji exclusion
    "\U00002692",
    # "\U00002693",  # twemoji exclusion
    "\U00002694",
    "\U00002695",
    "\U00002696",
    "\U00002697",
    "\U00002699",
    "\U0000269b",
    "\U0000269c",
    "\U000026a0",
    # "\U000026a1",  # twemoji exclusion
    # "\U000026a7",  # twemoji exclusion
    # "\U000026aa",  # twemoji exclusion
    # "\U000026ab",  # twemoji exclusion
    "\U000026b0",
    "\U000026b1",
    # "\U000026bd",  # twemoji exclusion
    # "\U000026be",  # twemoji exclusion
    # "\U000026c4",  # twemoji exclusion
    # "\U000026c5",  # twemoji exclusion
    "\U000026c8",
    "\U000026cf",
    "\U000026d1",
    "\U000026d3",
    # "\U000026d4",  # twemoji exclusion
    "\U000026e9",
    # "\U000026ea",  # twemoji exclusion
    "\U000026f0",
    "\U000026f1",
    # "\U000026f2",  # twemoji exclusion
    # "\U000026f3",  # twemoji exclusion
    "\U000026f4",
    # "\U000026f5",  # twemoji exclusion
    "\U000026f7",
    "\U000026f8",
    "\U000026f9",
    # "\U000026fa",  # twemoji exclusion
    # "\U000026fd",  # twemoji exclusion
    "\U00002702",
    "\U00002708",
    "\U00002709",
    "\U0000270c",
    "\U0000270d",
    "\U0000270f",
    "\U00002712",
    "\U00002714",
    "\U00002716",
    "\U0000271d",
    "\U00002721",
    "\U00002733",
    "\U00002734",
    "\U00002744",
    "\U00002747",
    # "\U00002753",  # twemoji exclusion
    # "\U00002757",  # twemoji exclusion
    "\U00002763",
    "\U00002764",
    "\U000027a1",
    "\U00002934",
    "\U00002935",
    "\U00002b05",
    "\U00002b06",
    "\U00002b07",
    # "\U00002b1b",  # twemoji exclusion
    # "\U00002b1c",  # twemoji exclusion
    # "\U00002b50",  # twemoji exclusion
    # "\U00002b55",  # twemoji exclusion
    "\U00003030",
    "\U0000303d",
    "\U00003297",
    "\U00003299",
    # "\U0001f004",  # twemoji exclusion
    "\U0001f170",
    "\U0001f171",
    "\U0001f17e",
    "\U0001f17f",
    "\U0001f202",
    # "\U0001f21a",  # twemoji exclusion
    # "\U0001f22f",  # twemoji exclusion
    "\U0001f237",
    # "\U0001f30d",  # twemoji exclusion
    # "\U0001f30e",  # twemoji exclusion
    # "\U0001f30f",  # twemoji exclusion
    # "\U0001f315",  # twemoji exclusion
    # "\U0001f31c",  # twemoji exclusion
    "\U0001f321",
    "\U0001f324",
    "\U0001f325",
    "\U0001f326",
    "\U0001f327",
    "\U0001f328",
    "\U0001f329",
    "\U0001f32a",
    "\U0001f32b",
    "\U0001f32c",
    "\U0001f336",
    # "\U0001f378",  # twemoji exclusion
    "\U0001f37d",
    # "\U0001f393",  # twemoji exclusion
    "\U0001f396",
    "\U0001f397",
    "\U0001f399",
    "\U0001f39a",
    "\U0001f39b",
    "\U0001f39e",
    "\U0001f39f",
    # "\U0001f3a7",  # twemoji exclusion
    # "\U0001f3ac",  # twemoji exclusion
    # "\U0001f3ad",  # twemoji exclusion
    # "\U0001f3ae",  # twemoji exclusion
    # "\U0001f3c2",  # twemoji exclusion
    # "\U0001f3c4",  # twemoji exclusion
    # "\U0001f3c6",  # twemoji exclusion
    # "\U0001f3ca",  # twemoji exclusion
    "\U0001f3cb",
    "\U0001f3cc",
    "\U0001f3cd",
    "\U0001f3ce",
    "\U0001f3d4",
    "\U0001f3d5",
    "\U0001f3d6",
    "\U0001f3d7",
    "\U0001f3d8",
    "\U0001f3d9",
    "\U0001f3da",
    "\U0001f3db",
    "\U0001f3dc",
    "\U0001f3dd",
    "\U0001f3de",
    "\U0001f3df",
    # "\U0001f3e0",  # twemoji exclusion
    # "\U0001f3ed",  # twemoji exclusion
    "\U0001f3f3",
    "\U0001f3f5",
    "\U0001f3f7",
    # "\U0001f408",  # twemoji exclusion
    # "\U0001f415",  # twemoji exclusion
    # "\U0001f41f",  # twemoji exclusion
    # "\U0001f426",  # twemoji exclusion
    "\U0001f43f",
    "\U0001f441",
    # "\U0001f442",  # twemoji exclusion
    # "\U0001f446",  # twemoji exclusion
    # "\U0001f447",  # twemoji exclusion
    # "\U0001f448",  # twemoji exclusion
    # "\U0001f449",  # twemoji exclusion
    # "\U0001f44d",  # twemoji exclusion
    # "\U0001f44e",  # twemoji exclusion
    # "\U0001f453",  # twemoji exclusion
    # "\U0001f46a",  # twemoji exclusion
    # "\U0001f47d",  # twemoji exclusion
    # "\U0001f4a3",  # twemoji exclusion
    # "\U0001f4b0",  # twemoji exclusion
    # "\U0001f4b3",  # twemoji exclusion
    # "\U0001f4bb",  # twemoji exclusion
    # "\U0001f4bf",  # twemoji exclusion
    # "\U0001f4cb",  # twemoji exclusion
    # "\U0001f4da",  # twemoji exclusion
    # "\U0001f4df",  # twemoji exclusion
    # "\U0001f4e4",  # twemoji exclusion
    # "\U0001f4e5",  # twemoji exclusion
    # "\U0001f4e6",  # twemoji exclusion
    # "\U0001f4ea",  # twemoji exclusion
    # "\U0001f4eb",  # twemoji exclusion
    # "\U0001f4ec",  # twemoji exclusion
    # "\U0001f4ed",  # twemoji exclusion
    # "\U0001f4f7",  # twemoji exclusion
    # "\U0001f4f9",  # twemoji exclusion
    # "\U0001f4fa",  # twemoji exclusion
    # "\U0001f4fb",  # twemoji exclusion
    "\U0001f4fd",
    # "\U0001f508",  # twemoji exclusion
    # "\U0001f50d",  # twemoji exclusion
    # "\U0001f512",  # twemoji exclusion
    # "\U0001f513",  # twemoji exclusion
    "\U0001f549",
    "\U0001f54a",
    # "\U0001f550",  # twemoji exclusion
    # "\U0001f551",  # twemoji exclusion
    # "\U0001f552",  # twemoji exclusion
    # "\U0001f553",  # twemoji exclusion
    # "\U0001f554",  # twemoji exclusion
    # "\U0001f555",  # twemoji exclusion
    # "\U0001f556",  # twemoji exclusion
    # "\U0001f557",  # twemoji exclusion
    # "\U0001f558",  # twemoji exclusion
    # "\U0001f559",  # twemoji exclusion
    # "\U0001f55a",  # twemoji exclusion
    # "\U0001f55b",  # twemoji exclusion
    # "\U0001f55c",  # twemoji exclusion
    # "\U0001f55d",  # twemoji exclusion
    # "\U0001f55e",  # twemoji exclusion
    # "\U0001f55f",  # twemoji exclusion
    # "\U0001f560",  # twemoji exclusion
    # "\U0001f561",  # twemoji exclusion
    # "\U0001f562",  # twemoji exclusion
    # "\U0001f563",  # twemoji exclusion
    # "\U0001f564",  # twemoji exclusion
    # "\U0001f565",  # twemoji exclusion
    # "\U0001f566",  # twemoji exclusion
    # "\U0001f567",  # twemoji exclusion
    "\U0001f56f",
    "\U0001f570",
    "\U0001f573",
    "\U0001f574",
    "\U0001f575",
    "\U0001f576",
    "\U0001f577",
    "\U0001f578",
    "\U0001f579",
    "\U0001f587",
    "\U0001f58a",
    "\U0001f58b",
    "\U0001f58c",
    "\U0001f58d",
    "\U0001f590",
    "\U0001f5a5",
    "\U0001f5a8",
    "\U0001f5b1",
    "\U0001f5b2",
    "\U0001f5bc",
    "\U0001f5c2",
    "\U0001f5c3",
    "\U0001f5c4",
    "\U0001f5d1",
    "\U0001f5d2",
    "\U0001f5d3",
    "\U0001f5dc",
    "\U0001f5dd",
    "\U0001f5de",
    "\U0001f5e1",
    "\U0001f5e3",
    "\U0001f5e8",
    "\U0001f5ef",
    "\U0001f5f3",
    "\U0001f5fa",
    # "\U0001f610",  # twemoji exclusion
    # "\U0001f687",  # twemoji exclusion
    # "\U0001f68d",  # twemoji exclusion
    # "\U0001f691",  # twemoji exclusion
    # "\U0001f694",  # twemoji exclusion
    # "\U0001f698",  # twemoji exclusion
    # "\U0001f6ad",  # twemoji exclusion
    # "\U0001f6b2",  # twemoji exclusion
    # "\U0001f6b9",  # twemoji exclusion
    # "\U0001f6ba",  # twemoji exclusion
    # "\U0001f6bc",  # twemoji exclusion
    "\U0001f6cb",
    "\U0001f6cd",
    "\U0001f6ce",
    "\U0001f6cf",
    "\U0001f6e0",
    "\U0001f6e1",
    "\U0001f6e2",
    "\U0001f6e3",
    "\U0001f6e4",
    "\U0001f6e5",
    "\U0001f6e9",
    "\U0001f6f0",
    "\U0001f6f3",
)
