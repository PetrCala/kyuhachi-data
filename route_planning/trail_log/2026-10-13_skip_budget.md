# Kyuhachi skip budget, as of Tue 13 Oct 2026

## Sources
- Route line: kyuhachi-data/route_planning/final_route/00_full_route.gpx (commit e44a91d, 2026-06-25 21:24 +0200), 1205.0 km. Same line as the app's active route "Loop around Kyushu (06-25)".
- Stops on the line: route_planning/handdrawn_loop_analysis.json, 119 stops (commit c3a04a0, 2026-06-30).
- Day plan: route_planning/plan_octnov.md + .json (commit 97dbc20, 2026-08-11 11:56 +0200). Nothing in route_planning/ changed after that; the data repo's newest commit (04cce1b, 2026-09-17) is catalog-only.
- kyuhachi/_archive: Python prototype only, no committed route or plan. Not used.
- Position: /journey_days 2026-10-12 track ends at km 194.6, at 白鳥温泉. Last synced visit: #22 白鳥温泉上湯 (Oct 12 21:52 JST).
- Hours: live Firestore /onsens catalog (public read), fetched 2026-10-13.

## Counts
| | |
|---|---|
| Onsens on the route (within 2 km of the line) | 119 (115 core + 4 optional buffer: #96 赤川, #114 生石, #115 賀来, #116 高崎山) |
| Behind you (stops 1 to 22) | 22 |
| Ahead (stops 23 to 119) | 97 (93 core + 4 buffer), 36 of them 不定休 |
| Entered / skipped so far (your numbers) | 19 / 3 |
| Synced visits in Firestore | 18 (no synced visit for #11, #12, #17, #21) |

## Skip budget (19 entered)
| | |
|---|---|
| Still needed | 69 |
| Skip budget on the 97 ahead | 28 (24 if you skip the 4 buffer detours) |
| Required hit rate | 71.1% (74.2% on the 93 core) |
| If it's really 18 entered / 4 skipped | need 70, budget 27, 72.2% |

Re-plan from km 195.1 on Oct 13 (plan's own day profile continued from walking day 9, live catalog hours, skip-lean, 240 min door wait):
80 planned visits of 97 → 99 total, 88 reached on Thu Nov 12 (day 31), finish Sat Nov 14, 18 days of slack to Dec 2.
The plan itself spends 17 skips (8 closed, 7 late, 2 early), leaving 11 for surprises.
Shifting the whole schedule by one day gives 81 visits (finish Nov 15), by two days 84 (finish Nov 16, 16 days slack): the weekday alignment at Aso and at 長湯 is what moves.

## Where a closure hurts most
1. Days 8 to 10 (Oct 20 to 22, km 422 to 534, Ashikita coast → Aso south rim): 4 onsens on the line, 0 planned visits. #39 湯浦 opens 15:00, #40 日奈久 closed Tue, #41 垂玉 closed Oct 22 (2nd/4th Thursday rule), #42 地獄温泉 last entry 15:00. Plus the 84 km gap 日奈久→垂玉. Reaching 日奈久 on a Wed and 垂玉 on a Fri turns two of these into visits.
2. Single-onsen days: Oct 14 (#28 船津†), Oct 18 (#36 十三奉行, closed Wed until end of Oct), Oct 28 (#58 嬉野†), Oct 30 (#61 佐賀大和†).
3. #59 波佐見 湯治楼 (Thu Oct 29, 不定休): the only 長崎 onsen on the route. Call 0956-76-9008 a day or two ahead.
4. Nov 10 長湯 cluster: 3 of 6 lost to Tuesday closures (赤川 Tue to Thu, 七里田 Tue, 山の湯かずよ Tue + Fri).
5. Onsen-free stretches of 25 km or more ahead: 吉松→船津 41, 紫尾→川内高城 29, 十三奉行→湯の鶴 25, 日奈久→垂玉 84, 阿蘇内牧→菊池 32, 久留米→嬉野 64, 武雄→佐賀大和 39, 古湯→久留米 38, 博多→あさくら 28.

## Catalog flags
- No onsen on the remaining route is inactive. The catalog's one retired onsen (神の湯, 紫尾温泉, retired Aug 2026) is not on the route. All 97 ahead are in your challenge's eligible snapshot.
- The catalog has no "temporarily closed" flag; closures only show up as hours. The live curated closed days differ from the plan's parse on 12 stops ahead (the table uses the live ones):
  - more closed than the plan knew: #62 湯招花 Tue+Wed, #96 赤川 Tue to Thu, #99 山の湯かずよ Tue+Fri, #105 束の間 Wed+Thu, #87 豊礼の湯 Wed (plan said Sun), #67 山ぼうし Thu + last Fri, #41 垂玉 Wed + 2nd/4th Thu
  - less closed: #60 武雄 元湯 open daily, #55 船小屋 Tue only, #50 旅館平山 Mon only, #70 富士の苑 open Tue from 16:00
  - #36 十三奉行: Wed closures run July to October (same as the plan)

## Per-day table
| day | date | km (cum km) | on line | plan ✓ | plan ✗ | entries after | skip budget left | onsens on the line (✓ planned visit, ✗ planned skip; † 不定休, B optional buffer) |
|---|---|---|---|---|---|---|---|---|
| 1 | 火 10-13 | 29 (195→224) | 5 | 4 | 1 | 23 | 27 | #23 加久藤温泉† ✗early, #24 あきしげゆ温泉 ✓, #25 京町温泉 ✓, #26 吉松温泉 ✓, #27 吉松温泉 ✓ |
| 2 | 水 10-14 | 34 (224→258) | 1 | 1 | 0 | 24 | 27 | #28 船津温泉† ✓ |
| 3 | 木 10-15 | 36 (258→293) | 3 | 3 | 0 | 27 | 27 | #29 滝の湯 ✓, #30 市比野温泉† ✓, #31 入来温泉† ✓ |
| 4 | 金 10-16 | 36 (293→329) | 2 | 2 | 0 | 29 | 27 | #32 宮之城温泉 ✓, #33 紫尾温泉 ✓ |
| 5 | 土 10-17 | 36 (329→364) | 2 | 2 | 0 | 31 | 27 | #34 川内高城温泉 ✓, #35 阿久根温泉† ✓ |
| 6 | 日 10-18 | 22 (364→386) | 1 | 1 | 0 | 32 | 27 | #36 十三奉行温泉 ✓ |
| 7 | 月 10-19 | 36 (386→422) | 2 | 2 | 0 | 34 | 27 | #37 湯の鶴温泉† ✓, #38 湯の児温泉 ✓ |
| 8 | 火 10-20 | 36 (422→458) | 2 | 0 | 2 | 34 | 25 | #39 湯浦温泉† ✗early, #40 日奈久温泉 ✗closed |
| 9 | 水 10-21 | 36 (458→494) | 0 | 0 | 0 | 34 | 25 | (none) |
| 10 | 木 10-22 | 40 (494→534) | 2 | 0 | 2 | 34 | 23 | #41 垂玉温泉 ✗closed, #42 地獄温泉† ✗late |
| 11 | 金 10-23 | 36 (534→570) | 2 | 2 | 0 | 36 | 23 | #43 大阿蘇　火の山温泉† ✓, #44 阿蘇内牧温泉 ✓ |
| 12 | 土 10-24 | 33 (570→603) | 4 | 4 | 0 | 40 | 23 | #45 菊池温泉 ✓, #46 泗水温泉 ✓, #47 亀の甲温泉 ✓, #48 辰頭温泉 ✓ |
| 13 | 日 10-25 | 22 (603→625) | 5 | 5 | 0 | 45 | 23 | #49 宝田温泉† ✓, #50 植木温泉 ✓, #51 山鹿温泉 ✓, #52 山鹿温泉† ✓, #53 平山温泉† ✓ |
| 14 | 月 10-26 | 34 (625→659) | 2 | 2 | 0 | 47 | 23 | #54 三加和温泉 ✓, #55 船小屋温泉 ✓ |
| 15 | 火 10-27 | 33 (659→692) | 2 | 1 | 1 | 48 | 22 | #56 大川温泉 ✗closed, #57 久留米温泉 ✓ |
| 16 | 水 10-28 | 36 (692→728) | 1 | 1 | 0 | 49 | 22 | #58 嬉野温泉† ✓ |
| 17 | 木 10-29 | 38 (728→766) | 2 | 2 | 0 | 51 | 22 | #59 波佐見温泉† ✓, #60 武雄温泉 ✓ |
| 18 | 金 10-30 | 39 (766→805) | 1 | 1 | 0 | 52 | 22 | #61 佐賀大和温泉† ✓ |
| 19 | 土 10-31 | 36 (805→841) | 3 | 3 | 0 | 55 | 22 | #62 熊の川温泉 ✓, #63 熊の川温泉 ✓, #64 古湯温泉† ✓ |
| 20 | 日 11-01 | 28 (841→869) | 3 | 2 | 1 | 57 | 21 | #65 久留米温泉 ✓, #66 久留米温泉 ✗late, #67 鳥栖温泉 ✓ |
| 21 | 月 11-02 | 36 (869→905) | 3 | 3 | 0 | 60 | 21 | #68 二日市温泉 ✓, #69 博多温泉 ✓, #70 博多温泉 ✓ |
| 22 | 火 11-03 | 36 (905→941) | 4 | 4 | 0 | 64 | 21 | #71 あさくら温泉 ✓, #72 甘木温泉 ✓, #73 吉井温泉† ✓, #74 原鶴温泉† ✓ |
| 23 | 水 11-04 | rest | 0 | 0 | 0 | 64 | 21 | planned zero-km rest day |
| 24 | 木 11-05 | 19 (941→960) | 5 | 4 | 1 | 68 | 20 | #75 奥原鶴温泉 とよとみの湯† ✓, #76 筑後川温泉 ✓, #77 筑後川温泉 ✓, #78 林田温泉 ✗closed, #79 夜明温泉 ✓ |
| 25 | 金 11-06 | 34 (960→990) | 3 | 3 | 0 | 71 | 20 | #80 天ヶ瀬温泉† ✓, #81 天ヶ瀬温泉† ✓, #82 杖立温泉 ✓ |
| 26 | 土 11-07 | 29 (990→1019) | 4 | 3 | 1 | 74 | 19 | #83 杖立温泉† ✓, #84 川底温泉† ✓, #85 壁湯天然洞窟温泉† ✗late, #86 岳の湯温泉 ✓ |
| 27 | 日 11-08 | 28 (1019→1046) | 5 | 4 | 1 | 78 | 18 | #87 岳の湯温泉 ✓, #88 日平温泉 ✓, #89 黒川温泉† ✓, #90 小田温泉† ✗late, #91 筋湯温泉† ✓ |
| 28 | 月 11-09 | 22 (1046→1068) | 4 | 4 | 0 | 82 | 18 | #92 九酔渓温泉† ✓, #93 筌の口温泉 ✓, #94 筌の口温泉† ✓, #95 星生温泉† ✓ |
| 29 | 火 11-10 | 30 (1068→1097) | 6 | 3 | 3 | 85 | 15 | #96 赤川温泉ᴮ ✗closed, #97 法華院温泉 ✓, #98 七里田温泉 ✗closed, #99 長湯温泉 ✗closed, #100 長湯温泉† ✓, #101 長湯温泉 ✓ |
| 30 | 水 11-11 | 37 (1097→1134) | 2 | 2 | 0 | 87 | 15 | #102 湯平温泉† ✓, #103 由布院温泉 ✓ |
| 31 | 木 11-12 | 30 (1134→1163) | 5 | 3 | 2 | 90 | 11 | #104 由布院温泉† ✓, #105 由布院温泉 ✗closed, #106 塚原温泉 ✓, #107 明礬温泉 ✓, #108 明礬温泉† ✗late |
| 32 | 金 11-13 | 27 (1163→1190) | 6 | 6 | 0 | 96 | 5 | #109 明礬温泉 ✓, #110 鉄輪温泉† ✓, #111 鉄輪温泉 ✓, #112 亀川温泉 ✓, #113 別府温泉† ✓, #114 生石温泉ᴮ ✓ |
| 33 | 土 11-14 | 16 (1190→1205) | 5 | 3 | 2 | 99 | 0 | #115 賀来温泉ᴮ ✓, #116 高崎山温泉ᴮ ✓, #117 別府温泉 ✓, #118 別府温泉 ✗late, #119 浜脇温泉 ✗late |
