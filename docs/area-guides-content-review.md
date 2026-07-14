# Area guides content review

A human-readable, side-by-side review of every published area guide, produced as
the **pre-human-review spot-check** for the area-guides feature. Source of truth:
[`data/area_guides_curated.json`](../data/area_guides_curated.json); region model
(areaId, prefecture): [`data/area-regions.json`](../data/area-regions.json);
schema and policy: [`docs/area-guides-schema.md`](area-guides-schema.md).

**Status:** content is already live at publish version 1. Nothing here has been
re-published. Two clear internal-consistency fixes were applied to the curated
JSON in the same PR (marked ✎ below); everything else is left as a flagged
finding for a human owner to decide. To roll out the fixes, a human runs
`python publisher/publish_area_guides.py` (dry-run) then `--commit`, which bumps
the version and writes production.

## Method

- **Factual re-verification.** 7 parallel research agents (one per region pair)
  re-checked every checkable claim (designations, historical periods/dates,
  "largest/first/only" superlatives, place names) against reputable sources:
  official tourism/government sites, Wikipedia, established travel guides.
- **Bilingual + tone + policy pass.** A full EN↔JA fidelity read of every field
  (name, tagline, each section body and highlights), plus a policy scan for
  time-bound content, prices, dated events, and named businesses, and a tone /
  typo / AI-tell check on both languages.
- **Scope of auto-fixes.** Only clear, uncontroversial errors were changed in the
  JSON (an internal contradiction and a script inconsistency). Matters of taste,
  transcreation latitude, and anything debatable are flagged, not "fixed."

## Findings summary

Severity: **blocker** (factual error / policy violation / misinforming
mistranslation) · **should-fix** (misleading or imprecise, worth an editor's
call) · **nit** (minor polish). Status: **✎ Fixed this PR** or **Flagged** (for
the human owner).

| # | Severity | Region | Section | Issue | Suggested change | Status |
|---|---|---|---|---|---|---|
| 1 | should-fix | Aso & Oguni | specialties | Internal contradiction: the highlight read だご汁 (*dago-jiru*, the local Kumamoto name) while the EN body/highlight and JA body used *dango-jiru* / 団子汁 (the Ōita form). MAFF lists だご汁 as the Kumamoto dish, だんご汁 as Ōita's. | Unify to the local form: *dago-jiru* / だご汁 in body and highlight. | ✎ Fixed |
| 2 | nit | Hita & Yabakei | tagline | JA tagline wrote the place name 耶馬渓 in hiragana (やばけい), inconsistent with the region name and the attractions-section JA, which both use the kanji 耶馬渓. | Write 耶馬渓 in kanji (`水郷と耶馬渓の里`). Pure script normalization, meaning unchanged. | ✎ Fixed |
| 3 | should-fix | Kuju & Taketa | tagline | EN "…and highland **moors**" and JA "…高原の**湯**" (highland hot springs) name different second features. The attractions section (JA 湿原 = wetlands) suggests "moors/wetlands" was the intent. | Align the pair, e.g. JA `炭酸泉と高原の湿原`, or EN "…and highland spa country". Editorial call. | Flagged |
| 4 | should-fix | Yamaga & Kikuchi | history | English reuses "Kikuchi" for both the **medieval Kikuchi clan** (菊池氏) and the **ancient Kikuchi Castle** (鞠智城, a 7th-c. frontier fort ~500 yrs older). Both statements are factually correct, but the adjacency can imply the clan built the fort. JA uses distinct kanji, so the risk is EN-only. | Optionally add a clause that the fort predates the clan, or disambiguate the English name. | Flagged |
| 5 | nit | Nagasaki | tagline | EN "Japan's historic window to the world" and JA "和華蘭の異国情緒" (the exotic *wakaran* ambience) diverge notably in emphasis, more than the other taglines. | Decide whether to bring the two closer. Both are apt for Nagasaki. | Flagged |
| 6 | nit | Yufuin | name / spelling | JA uses 湯布院 (the post-1955-merger district spelling); the hot spring's official name is 由布院. Both read "Yufuin." An onsen-guide could prefer 由布院. | Decide 湯布院 vs 由布院. Either is defensible. | Flagged |
| 7 | nit | Yufuin | tagline | EN adds "**arts**" ("arts-and-onsen retreat") that JA "由布岳のふもとの湯の里" (hot-spring village at the foot of Mount Yufu) does not carry. Normal transcreation. | Optional: add an "arts" nuance to JA, or drop it from EN. | Flagged |
| 8 | nit | Beppu | attractions | Body names "the **Beppu Ropeway**," a commercial operator, which brushes the "no named businesses" line. (Highlights correctly list Mount Tsurumi, not the operator.) | Optional: "a ropeway climbs Mount Tsurumi." | Flagged |
| 9 | nit | Kunisaki & Usa | attractions | EN calls the Kumano Magaibutsu "giant **Buddha** figures"; one of the two carvings is Fudō Myōō, a wisdom king (*myōō*), not a Buddha. JA 磨崖仏 is broader and stays accurate. "Buddha figures" is common loose usage. | Optional: "giant **Buddhist** figures / rock carvings." | Flagged |
| 10 | nit | Kunisaki & Usa | culture | *shichitoi* (七島藺) called "a **rush** grass"; botanically it's a **sedge** (Cyperaceae). English guides commonly say "rush." | Optional: "a sedge." | Flagged |
| 11 | nit | Kunisaki & Usa | tagline | EN "stone Buddhas and **shrines**" renders JA "石仏と**神仏習合**の里" (…and Shinto-Buddhist syncretism); "shrines" softens the syncretism idea (not wrong; Usa Jingū is present). | Optional: "…and Shinto-Buddhist syncretism." | Flagged |
| 12 | nit | Amakusa & Ashikita | tagline | EN "churches and **sunsets**" vs JA "天草の**海**と教会" (sea and churches): the second element differs (sunsets ↔ sea). | Optional align. | Flagged |
| 13 | nit | Amakusa & Ashikita | produce | Dekopon called "a sweet seedless **mandarin**"; botanically a *tangor* (Kiyomi × Ponkan) and usually- but not always-seedless. JA "柑橘/citrus" is looser and safer. | Optional: "a sweet, largely seedless citrus (a mandarin hybrid)." | Flagged |
| 14 | nit | Miyazaki | tagline | EN "Sun, **surf** and the land of myth" includes surf; JA "日向路の神話と南国" has no surf equivalent (神話 = myth, 南国 = sunny south). | Optional align. | Flagged |
| 15 | nit | Aso & Oguni | attractions | JA waterfall name written 鍋**ケ**滝 (full-size ケ); the standard/official form is 鍋**ヶ**滝 (small ヶ). | Optional: normalize ケ → ヶ. | Flagged |
| 16 | nit | Yamaga & Kikuchi | history | "the Kikuchi clan … left their name across the landscape" slightly reverses the record: the clan took its name **from** Kikuchi district, not vice versa. The regional association is genuine. | Optional reword. | Flagged |

**No blockers.** No factual errors survived re-verification, and no
policy-violating content (opening hours, prices, dated one-time events, named
shops/restaurants) was found. Recurring traditional festivals and customs
(Karatsu Kunchi, *noyaki*, *yokagura*) are evergreen cultural content and are in
policy. The prior pass's two corrections (Kunisaki Rokugo Manzan = Nara period;
Yamaga lanterns "golden" not "gilded") were both re-confirmed correct.

## Fact-check: notable claims re-verified against sources

Every checkable claim was re-verified; the superlatives and designations most
worth a second look all held:

- **Beppu**: "one of the largest volumes of hot-spring water in the world" is
  defensible (commonly cited 2nd globally after Yellowstone, 1st in Japan).
  Kabosu ≈ 98 to 99% Oita. Sand bath term *sunayu* (砂湯) correct.
- **Kuju/Taketa**: Nagayu carbonated springs + drinking cure; Oita #1 in dried
  shiitake (~48% national); Tadewara & Bogatsuru Ramsar-listed (2005); Oka Castle
  linked to *Kōjō no Tsuki*.
- **Hita**: Edo shogunate direct-control territory (天領); Kangien among the
  Edo era's largest private academies; Hita a major geta production center.
- **Kunisaki/Usa**: Usa Jingū is the head shrine (総本宮) of ~40,000+ Hachiman
  shrines; **Rokugo Manzan founding = Nara period (718, Ninmon legend)**,
  re-confirmed, prior fix correct; shichitoi is a Kunisaki-only GI crop.
- **Aso/Oguni**: akaushi red cattle; caldera correctly hedged as "one of the
  largest" (JA 世界最大級 / 世界有数) not "the largest"; Nabegataki is a
  walk-behind falls; Aso Shrine among Japan's oldest.
- **Yamaga/Kikuchi**: Yachiyoza (1910, Important Cultural Property); Kikuchi
  Castle (鞠智城) correctly *ancient* (7th-c. Dazaifu-defense fort); Yamaga tōrō
  frameless washi lanterns, "golden" correct; Kikuchi rice repeated 特A grade.
- **Hitoyoshi/Kuma**: Kuma shōchū is a WTO/TRIPS geographical indication; Aoi
  Aso Shrine main buildings are a National Treasure (2008); Kuma River one of
  Japan's three most rapid rivers; Sagara clan ~700 years (1198 to 1868).
- **Amakusa/Ashikita**: Sakitsu is the one Kumamoto component of the
  Nagasaki-region Hidden Christian World Heritage sites (2018); Shimabara-Amakusa
  uprising (1637 to 38); resident wild dolphin pod.
- **Fukuoka**: Yame ≈ 45% of Japan's gyokuro; Nanzoin bronze reclining Buddha
  (world's largest bronze statue); Genkō Bōrui Mongol-invasion walls; Hakata has
  Japan's largest concentration of yatai.
- **Saga**: Saga #1 in Ariake nori; Arita birthplace of Japanese porcelain
  (~1616), exported via Imari; Saga domain's reverberatory furnace / Mietsu dock
  (Meiji Industrial Revolution WH); Karatsu Kunchi 14 hikiyama floats.
- **Nagasaki**: **#1 loquat producer (~34% national)** confirmed; "sole
  official window to Europe and China" correctly scoped (the four-gateway trap
  avoided); Ōura Church is Japan's oldest surviving church (National Treasure).
- **Miyazaki**: Miyazaki beef 4× consecutive Wagyu Olympics; mango a "major
  producer" (#2 after Okinawa) is safe; Saitobaru 300+ kofun; Takachiho yokagura
  Important Intangible Folk Cultural Property.
- **Kagoshima**: #1 sweet-potato producer (~40%); green tea "top producer" now
  understated (overtook Shizuoka for #1 in 2024), kept as evergreen "top";
  Sakurajima daikon (Guinness heaviest) and komikan (smallest) superlatives hold.

---

# Side-by-side content (as published, post-fix)

Ordered as in the source. Each region shows its `areaId`, then name, tagline, and
every section (body + highlights) in EN and 日本語. Rows marked ✎ contain a fix
applied in this PR.

## 1. Beppu (`oita-beppu`)

areaId `7fe5ceb9-b92c-4480-bdf8-0e2d97a85ae3` · 大分県

| Field | English | 日本語 |
|---|---|---|
| Name | Beppu | 別府 |
| Tagline | Japan's onsen capital | 日本一の湯のまち |
| **Specialties** | Beppu cooks with its steam. Jigoku-mushi, food steamed over natural hot-spring vents, is the signature local way to eat, and toriten, Oita's batter-fried chicken, is a regional staple. | 別府は温泉の蒸気で料理をします。地獄蒸しは源泉の噴気で食材を蒸す名物で、大分名物のとり天も広く親しまれています。 |
| ↳ Highlights | Jigoku-mushi steamed dishes · Toriten (chicken tempura) | 地獄蒸し · とり天 |
| **Produce** | Oita is known for the kabosu, a fragrant green citrus squeezed over grilled fish and hotpots. Seafood from Beppu Bay rounds out the local table. | 大分はかぼすの産地として知られ、焼き魚や鍋にしぼって使います。別府湾の海の幸も食卓を彩ります。 |
| ↳ Highlights | Kabosu citrus | かぼす |
| **Attractions** | The jigoku, or Hells, are a set of vividly coloured hot-spring pools meant for viewing rather than bathing. Above town, the Beppu Ropeway climbs Mount Tsurumi for a sweeping view over the bay. | 地獄めぐりは、入浴ではなく鑑賞のための色鮮やかな源泉の数々です。町の上手からは別府ロープウェイで鶴見岳に登り、別府湾を一望できます。 |
| ↳ Highlights | The Hells (jigoku meguri) · Mount Tsurumi | 地獄めぐり · 鶴見岳 |
| **History** | Beppu produces one of the largest volumes of hot-spring water in the world, across a group of districts long known together as the Beppu Hatto, the Eight Hot Springs of Beppu. It grew over the modern era from a therapeutic bathing town into Japan's best-known onsen resort. | 別府は世界有数の湧出量を誇り、古くから別府八湯と総称される温泉地の集まりです。近代を通じて湯治のまちから日本を代表する温泉リゾートへと発展しました。 |
| **Culture** | Beyond ordinary baths, Beppu is famous for its sand baths, where you are buried in naturally heated sand, and steam baths. Public bathhouse culture is part of daily life here. | ふつうの湯船だけでなく、地熱で温めた砂に埋もれる砂湯や、蒸し湯でも知られています。共同浴場の文化が暮らしに根づいています。 |
| ↳ Highlights | Sand bath (sunayu) | 砂湯 |

*Note (finding 8): "Beppu Ropeway" in the attractions body names an operator; consider "a ropeway climbs Mount Tsurumi."*

## 2. Yufuin (`oita-yufuin`)

areaId `7d606144-d133-4e22-94ce-360ba705078a` · 大分県

| Field | English | 日本語 |
|---|---|---|
| Name | Yufuin | 湯布院 |
| Tagline | An arts-and-onsen retreat under Mount Yufu | 由布岳のふもとの湯の里 |
| **Specialties** | Yufuin leans toward a slow, cafe-and-craft style of onsen town. Bungo beef, Oita's premium wagyu, is the local highlight, alongside dairy sweets made from highland milk. | 湯布院は、カフェや工芸を楽しむゆったりとした温泉地です。大分のブランド和牛である豊後牛が名物で、高原の牛乳を使った乳製品のスイーツも人気です。 |
| ↳ Highlights | Bungo beef | 豊後牛 |
| **Attractions** | Lake Kinrin, a small spring-fed pond that steams on cold mornings, sits at the heart of the town. The twin-peaked Mount Yufu rises over the basin and is a popular half-day climb. | 町の中心には、寒い朝に湯気が立つ湧水の池、金鱗湖があります。盆地の上にそびえる双耳峰の由布岳は、半日で楽しめる登山として人気です。 |
| ↳ Highlights | Lake Kinrin · Mount Yufu | 金鱗湖 · 由布岳 |
| **History** | Yufuin developed as a quieter counterpoint to nearby Beppu. Local residents deliberately resisted large-scale resort development to preserve the rural landscape, shaping the small-inn character the town is known for today. | 湯布院は、近隣の別府とは対照的に、静かな温泉地として歩んできました。大規模な開発をあえて避けて田園風景を守ろうとした住民の取り組みが、今日の小さな宿が並ぶ町並みを形づくりました。 |
| **Culture** | The town is dotted with small art galleries, craft workshops and museums, giving it a reputation as an artsy retreat. Ryokan hospitality and landscape views are central to the experience. | 町には小さな美術館やギャラリー、工房が点在し、芸術的な保養地として知られています。旅館のもてなしと景観を楽しむ滞在が魅力です。 |

*Notes (findings 6, 7): JA name 湯布院 vs the onsen's official 由布院; EN tagline adds "arts" not in JA. Both editorial.*

## 3. Kuju & Taketa (`oita-kuju`)

areaId `658a7138-688f-4c8d-aa32-3542a0842a5a` · 大分県

| Field | English | 日本語 |
|---|---|---|
| Name | Kuju & Taketa | くじゅう・竹田 |
| Tagline | Carbonated springs and highland moors | 炭酸泉と高原の湯 |
| **Specialties** | The Nagayu area is celebrated for carbonated springs, whose carbon-dioxide-rich water leaves fine bubbles on the skin. Spa water is also taken as a drinking cure here. | 長湯温泉は炭酸泉で名高く、二酸化炭素を多く含む湯が肌に細かな泡をまといます。飲泉の文化も残っています。 |
| ↳ Highlights | Carbonated springs | 炭酸泉 |
| **Produce** | The cool highlands produce vegetables and dairy, and Oita is Japan's leading producer of dried shiitake mushrooms. Bungo beef is raised in the surrounding hills. | 涼しい高原では野菜や乳製品がつくられ、大分は干し椎茸の生産量で全国一を誇ります。周囲の山あいでは豊後牛も育てられています。 |
| ↳ Highlights | Dried shiitake | 干し椎茸 |
| **Attractions** | The Kuju mountain range and the Tadewara and Bogatsuru wetlands offer some of Kyushu's best highland walking, with the wetlands recognised under the Ramsar Convention. In Taketa, the mountaintop ruins of Oka Castle command a wide view of the valley. | くじゅう連山とタデ原・坊ガツルの湿原は、九州でも屈指の高原歩きの舞台で、湿原はラムサール条約にも登録されています。竹田では、山上の岡城跡が谷を見晴らします。 |
| ↳ Highlights | Kuju mountains · Oka Castle ruins | くじゅう連山 · 岡城跡 |
| **History** | Taketa was the castle town of the Oka domain, and the ruins of Oka Castle are said to have inspired the classic song Kojo no Tsuki, Moon over the Ruined Castle. The area keeps a quiet samurai-town character. | 竹田は岡藩の城下町で、岡城跡は名曲「荒城の月」の着想の地とされます。今も静かな城下町のたたずまいを残しています。 |

*Note (finding 3): tagline EN "highland moors" ≠ JA "高原の湯" (highland hot springs); align the pair.*

## 4. Hita & Yabakei (`oita-hita`)

areaId `0cf51afb-6b94-4f2d-b050-fe1e92288fc8` · 大分県

| Field | English | 日本語 |
|---|---|---|
| Name | Hita & Yabakei | 日田・耶馬渓 |
| Tagline ✎ | River town and carved-gorge country | 水郷と耶馬渓の里 |
| **Produce** | The Hita basin is prime cedar country, and Hita cedar is a well-known building timber. Local orchards grow pears and other fruit on the river plain. | 日田盆地は良質な杉の産地で、日田杉は建築用材として知られています。川沿いの平野では梨などの果樹も育てられています。 |
| ↳ Highlights | Hita cedar | 日田杉 |
| **Attractions** | Mameda-machi in Hita is a preserved district of Edo-period merchant houses and white-walled storefronts. To the north, the Yabakei gorge is famous for its craggy cliffs and the hand-carved Ao-no-Domon tunnel. | 日田の豆田町は、江戸時代の商家や白壁の町並みが残る保存地区です。北には、奇岩の断崖と手掘りの隧道「青の洞門」で知られる耶馬渓が広がります。 |
| ↳ Highlights | Mameda-machi old town · Yabakei gorge and Ao-no-Domon | 豆田町 · 耶馬渓・青の洞門 |
| **History** | In the Edo period Hita was governed directly by the shogunate as a centre of commerce and finance for the region. It was also home to the Kangien, one of the era's largest private academies. | 江戸時代の日田は幕府の直轄地として、地域の商業と金融の中心となりました。江戸期屈指の私塾であった咸宜園もこの地に開かれました。 |
| ↳ Highlights | Kangien academy | 咸宜園 |
| **Culture** | Hita has a long tradition of woodcraft, and the town is well known for its geta, wooden clogs. Cormorant fishing on the river is a summer custom that survives from earlier centuries. | 日田は木工の伝統が長く、下駄の産地として知られています。川で行われる鵜飼いは、古くから続く夏の風物詩です。 |

*✎ Fixed (finding 2): tagline JA やばけい → 耶馬渓 (kanji, matching the region name).*

## 5. Kunisaki & Usa (`oita-kunisaki`)

areaId `27110e0f-d339-4d4d-984b-07c050f925ea` · 大分県

| Field | English | 日本語 |
|---|---|---|
| Name | Kunisaki & Usa | 国東・宇佐 |
| Tagline | Peninsula of stone Buddhas and shrines | 石仏と神仏習合の里 |
| **Produce** | The peninsula is a noted producer of dried shiitake mushrooms grown on oak logs. Its coastal waters yield beltfish and other seafood. | 国東半島はクヌギの原木で育てる干し椎茸の名産地です。沿岸ではタチウオなどの海の幸も水揚げされます。 |
| ↳ Highlights | Dried shiitake | 干し椎茸 |
| **Attractions** | Usa Jingu is the head shrine of the tens of thousands of Hachiman shrines across Japan. The hills of the peninsula hold old temples of the Rokugo Manzan tradition and the Kumano Magaibutsu, giant Buddha figures carved into a rock face. | 宇佐神宮は、全国に数万社ある八幡宮の総本宮です。半島の山々には六郷満山の古寺が点在し、岩壁に刻まれた巨大な熊野磨崖仏も残ります。 |
| ↳ Highlights | Usa Jingu shrine · Kumano Magaibutsu rock Buddhas | 宇佐神宮 · 熊野磨崖仏 |
| **History** | Kunisaki is a cradle of shinbutsu-shugo, the historic fusion of Shinto and Buddhist worship. The Rokugo Manzan temple culture took shape here from the Nara period around the influence of Usa Jingu. | 国東は、神道と仏教が融合した神仏習合の一大中心地です。六郷満山の寺院文化は、宇佐神宮の影響のもとで奈良時代から形づくられました。 |
| **Culture** | The peninsula preserves an ascetic mountain-pilgrimage tradition tied to its temples. It is also historically known for shichitoi, a rush grass woven into high-grade tatami facing. | 半島には、寺院と結びついた山岳修行の伝統が受け継がれています。上質な畳表に織られる七島藺の産地としても知られてきました。 |

*Notes (findings 9 to 11): "Buddha figures" includes a Fudō Myōō (a myōō); "rush grass" is botanically a sedge; tagline "shrines" softens 神仏習合. All optional. Rokugo Manzan = Nara period re-confirmed.*

## 6. Aso & Oguni (`kumamoto-aso`)

areaId `fad65c15-fe08-4ea1-9543-7eba4e2f1f93` · 熊本県

| Field | English | 日本語 |
|---|---|---|
| Name | Aso & Oguni | 阿蘇・小国 |
| Tagline | One of the world's great calderas | 世界有数のカルデラ |
| **Specialties** ✎ | Aso is grazing country, and akaushi, the local red-haired beef cattle, is the signature meat. Hearty local dishes include dago-jiru, a miso soup with flat wheat dumplings, and takana-meshi rice mixed with pickled mustard greens. | 阿蘇は放牧の地で、赤牛と呼ばれる褐毛の牛が名物の肉です。小麦の団子を入れた味噌仕立てのだご汁や、高菜漬けを混ぜた高菜めしなど、素朴な郷土料理も親しまれています。 |
| ↳ Highlights | Aso akaushi beef · Dago-jiru | あか牛 · だご汁 |
| **Produce** | The highland pastures support dairy farming, including jersey milk, along with highland vegetables. The volcanic soil and cool climate shape the region's produce. | 高原の牧草地では、ジャージー牛乳をはじめとする酪農や高原野菜づくりが盛んです。火山性の土壌と涼しい気候が、この地の農産物を育てます。 |
| **Attractions** | Mount Aso is an active volcano ringed by one of the largest calderas in the world, with a smoking crater and vast grasslands. Nearby, Kurokawa Onsen is famous for its rustic streetscape of riverside inns, and Nabegataki is a waterfall you can walk behind. | 阿蘇山は、世界最大級のカルデラに囲まれた活火山で、噴煙を上げる火口と広大な草原が広がります。近くには、川沿いの宿がつくる素朴な湯の町並みで知られる黒川温泉や、裏側に回り込める鍋ケ滝があります。 |
| ↳ Highlights | Mount Aso crater · Kurokawa Onsen streetscape | 阿蘇中岳火口 · 黒川温泉 |
| **History** | The caldera was formed by enormous prehistoric eruptions, and Aso Shrine at its foot is one of Japan's oldest shrines. The grasslands are not wild but have been maintained for centuries by controlled burning. | カルデラは太古の巨大噴火によって形づくられ、ふもとの阿蘇神社は日本でも有数の古社です。草原は自然のままではなく、幾世紀にもわたる野焼きによって守られてきました。 |
| **Culture** | Grassland burning, or noyaki, each early spring keeps the open moors from returning to forest and is a defining ritual of local land management. Aso Shrine is also known for its centuries-old agricultural festivals. | 早春の野焼きは、草原が森に戻るのを防ぐもので、この地の土地管理を象徴する営みです。阿蘇神社は、古くから続く農耕の祭りでも知られています。 |
| ↳ Highlights | Noyaki grassland burning | 野焼き |

*✎ Fixed (finding 1): dago-jiru / だご汁 unified across body and highlight. Note (finding 15): JA 鍋ケ滝 → 鍋ヶ滝 (small ヶ) optional.*

## 7. Yamaga & Kikuchi (`kumamoto-yamaga-kikuchi`)

areaId `acb0740a-0261-4431-8394-fe1ee9630d01` · 熊本県

| Field | English | 日本語 |
|---|---|---|
| Name | Yamaga & Kikuchi | 山鹿・菊池 |
| Tagline | Lantern craft and clear-water valleys | 灯籠と渓流の里 |
| **Produce** | The northern Kumamoto plain is fertile rice country, and Kikuchi rice is well regarded. Clear river water and rich soil also support a range of vegetables. | 熊本県北の平野は豊かな米どころで、菊池米は評価が高いことで知られます。清らかな川の水と肥えた土は、さまざまな野菜も育てます。 |
| ↳ Highlights | Kikuchi rice | 菊池米 |
| **Attractions** | Yamaga is home to the Yachiyoza, a beautifully preserved Meiji-era playhouse still used for performances. The Kikuchi Gorge offers cool waterfalls and forest walks, and the ancient hill fort of Kikuchi Castle stands nearby. | 山鹿には、今も上演に使われる明治期の芝居小屋、八千代座が美しく保存されています。菊池渓谷では涼やかな滝と森の散策を楽しめ、近くには古代山城の鞠智城も残ります。 |
| ↳ Highlights | Yachiyoza playhouse · Kikuchi Gorge | 八千代座 · 菊池渓谷 |
| **History** | The medieval Kikuchi clan ruled this district for generations and left their name across the landscape. Kikuchi Castle was an ancient mountain fortress built in the style of early frontier defences. | 中世の菊池氏が代々この地を治め、その名は今も各地に残ります。鞠智城は、古代の辺境防備の様式でつくられた山城でした。 |
| **Culture** | Yamaga is famous for the Yamaga toro, golden paper lanterns crafted without any wooden or metal frame, and for the lantern dance in which performers balance them on their heads. The craft is a point of local pride. | 山鹿は、木や金具を使わずに和紙で組み上げる金色の山鹿灯籠と、それを頭に載せて舞う灯籠踊りで知られています。その技はこの地の誇りです。 |
| ↳ Highlights | Yamaga toro lanterns | 山鹿灯籠 |

*Notes (findings 4, 16): EN "Kikuchi" names both the medieval clan (菊池氏) and the ancient fort (鞠智城), facts correct, adjacency could mislead an EN reader; "left their name across the landscape" reverses the clan/district naming. Both optional. "Golden" re-confirmed correct.*

## 8. Hitoyoshi & Kuma (`kumamoto-hitoyoshi`)

areaId `43987844-7173-4005-a91a-c843c8873015` · 熊本県

| Field | English | 日本語 |
|---|---|---|
| Name | Hitoyoshi & Kuma | 人吉・球磨 |
| Tagline | Castle town on a swift river | 球磨川の城下町 |
| **Specialties** | The Kuma basin is the home of kuma shochu, a rice shochu whose name is legally protected as a regional appellation. Grilled eel is another local favourite. | 球磨盆地は、地名が地理的表示として保護されている米焼酎、球磨焼酎の産地です。うなぎの蒲焼きも地元で親しまれています。 |
| ↳ Highlights | Kuma shochu (rice) | 球磨焼酎 |
| **Attractions** | Hitoyoshi keeps the ruins of its riverside castle and the striking Aoi Aso Shrine, whose main buildings are designated a National Treasure. The fast-flowing Kuma River, one of the swiftest in Japan, is known for boat descents. | 人吉には、川沿いの城跡と、社殿が国宝に指定された青井阿蘇神社があります。日本三大急流のひとつに数えられる球磨川は、川下りで知られています。 |
| ↳ Highlights | Aoi Aso Shrine · Kuma River | 青井阿蘇神社 · 球磨川 |
| **History** | Hitoyoshi was ruled by the Sagara clan for roughly seven centuries, an unusually long unbroken hold over a single domain. That continuity left the area with a distinctive local culture and many old shrines and temples. | 人吉は相良氏によって約七百年にわたり治められ、ひとつの領地を絶えることなく守り続けた稀な例です。その連続性が、独特の地域文化と数多くの古い社寺を残しました。 |

*Region checks out; no findings.*

## 9. Amakusa & Ashikita (`kumamoto-amakusa`)

areaId `08248740-9d63-40c6-ba17-ccc6095518ac` · 熊本県

| Field | English | 日本語 |
|---|---|---|
| Name | Amakusa & Ashikita | 天草・芦北 |
| Tagline | Island coast of churches and sunsets | 天草の海と教会 |
| **Specialties** | The surrounding seas make this a seafood coast, with prized fish, sea urchin and prawns. Meals here are built around the day's catch. | 周囲を海に囲まれたこの地は海の幸が豊かで、旬の魚やウニ、車海老が味わえます。食卓はその日の水揚げを中心に組み立てられます。 |
| **Produce** | The mild coastal climate suits citrus, and Kumamoto is closely associated with the dekopon, a sweet seedless mandarin. Fishing remains central to the local economy. | 温暖な海辺の気候は柑橘に向き、熊本は甘くて種のない柑橘、デコポンと深く結びついています。漁業は今も地域の暮らしの柱です。 |
| ↳ Highlights | Dekopon citrus | デコポン |
| **Attractions** | The Amakusa islands are strung together by bridges over island-dotted seas famous for their sunsets and wild dolphins. Sakitsu Village, with its church set among fishing houses, is part of a group of hidden-Christian sites inscribed on the World Heritage list. | 天草の島々は橋で結ばれ、島影の浮かぶ海は夕日と野生のイルカで知られています。漁村に建つ教会がたたずむ崎津集落は、世界遺産に登録された潜伏キリシタン関連遺産のひとつです。 |
| ↳ Highlights | Amakusa islands · Sakitsu church village | 天草諸島 · 崎津集落 |
| **History** | In the early Edo period the area was a centre of the Shimabara-Amakusa uprising, a rebellion with strong ties to persecuted Christian communities. Hidden Christians kept their faith in secret here for generations. | 江戸時代初期、この地は、迫害されたキリシタンと深く結びついた島原・天草一揆の舞台となりました。潜伏キリシタンは、何世代にもわたり密かに信仰を守り継ぎました。 |

*Notes (findings 12, 13): tagline "sunsets" ↔ JA "海/sea"; dekopon "seedless mandarin" is loose (a tangor). Both optional.*

## 10. Fukuoka (`fukuoka`)

areaId `b128c6d2-64b0-424a-915d-3103a469cd43` · 福岡県

| Field | English | 日本語 |
|---|---|---|
| Name | Fukuoka | 福岡 |
| Tagline | Kyushu's gateway and food capital | 九州の玄関口・食のまち |
| **Specialties** | Fukuoka is one of Japan's great eating cities. Hakata tonkotsu ramen, with its rich pork-bone broth, motsunabe offal hotpot, and karashi mentaiko, spicy marinated pollock roe, are all local signatures. | 福岡は日本有数の食の街です。濃厚な豚骨スープの博多ラーメン、もつ鍋、そして辛子明太子は、いずれも土地を代表する味です。 |
| ↳ Highlights | Hakata tonkotsu ramen · Motsunabe hotpot · Karashi mentaiko | 博多ラーメン · もつ鍋 · 辛子明太子 |
| **Produce** | The prefecture grows the Amaou, a large sweet strawberry, and is a noted producer of Yame tea. Rice and vegetables come from the fertile Chikugo plain. | 県内では、大きく甘いいちご「あまおう」が育てられ、八女茶の産地としても知られています。米や野菜は肥沃な筑後平野から届きます。 |
| ↳ Highlights | Amaou strawberries · Yame tea | あまおう · 八女茶 |
| **Attractions** | Dazaifu Tenmangu, dedicated to the deity of learning, draws visitors year-round beneath its ancient camphor trees. Elsewhere the region offers the great reclining Buddha at Nanzoin and the willow-lined canals of Yanagawa, toured by pole-punted boat. | 学問の神をまつる太宰府天満宮は、古い楠の木々のもとに一年を通じて参拝者を集めます。ほかにも、南蔵院の巨大な涅槃像や、川下りの舟がゆく柳川の水郷があります。 |
| ↳ Highlights | Dazaifu Tenmangu shrine · Yanagawa canals | 太宰府天満宮 · 柳川の水郷 |
| **History** | Hakata was for centuries a leading port for trade with the Asian mainland, and nearby Dazaifu served as the ancient seat of regional government. The coast still holds remnants of the stone walls built to repel the Mongol invasions. | 博多は幾世紀にもわたり大陸交易の主要な港であり、近郊の太宰府は古代の地方政治の中心でした。海沿いには、元寇に備えて築かれた石塁の跡が今も残ります。 |
| **Culture** | Hakata's yatai, open-air food stalls that appear along the streets at night, are a cultural institution unique in scale to the city. Local crafts include Hakata-ori textiles and the finely modelled Hakata dolls. | 夜の街に並ぶ屋台は、その規模において福岡ならではの食文化です。伝統工芸には、博多織や、精巧な博多人形があります。 |
| ↳ Highlights | Hakata yatai stalls | 博多の屋台 |

*Region checks out; no findings.*

## 11. Saga (`saga`)

areaId `cb6d7d36-ec94-4ccf-9202-4fc4126e934f` · 佐賀県

| Field | English | 日本語 |
|---|---|---|
| Name | Saga | 佐賀 |
| Tagline | Porcelain towns and the Genkai Sea | やきものと玄界灘 |
| **Specialties** | Saga's Yobuko port is renowned for squid served so fresh it is still translucent. Saga beef is a premium wagyu brand, and the northern coast supplies much of the region's seafood. | 佐賀の呼子港は、透き通るほど新鮮なイカで名高い港です。佐賀牛は上質なブランド和牛で、北の海岸は地域の海の幸を支えています。 |
| ↳ Highlights | Yobuko squid · Saga beef | 呼子のイカ · 佐賀牛 |
| **Produce** | Saga is a major grower of nori seaweed on the Ariake Sea and produces the fragrant Ureshino green tea. The plains are known for rice and for sweet Shiroishi onions. | 佐賀は有明海の海苔の主要な産地であり、香り高い嬉野茶を生み出します。平野は米や、甘い白石たまねぎでも知られています。 |
| ↳ Highlights | Ariake Sea nori · Ureshino tea | 有明海の海苔 · 嬉野茶 |
| **Attractions** | The towns of Arita and Imari are the heart of Japanese porcelain, while Karatsu has its reconstructed castle and its own pottery tradition. At Yoshinogari, a large reconstructed settlement brings the Yayoi period to life. | 有田と伊万里の町は日本磁器の中心地で、唐津には再建された城と独自の焼き物の伝統があります。吉野ヶ里では、復元された大規模な集落が弥生時代の姿を伝えます。 |
| ↳ Highlights | Arita and Imari porcelain towns · Yoshinogari ruins | 有田・伊万里 · 吉野ヶ里遺跡 |
| **History** | Arita is the birthplace of Japanese porcelain, first fired in the early 1600s and later exported to Europe through the port of Imari. In the late Edo period the Saga domain became an early adopter of Western industrial technology. | 有田は日本磁器発祥の地で、一六〇〇年代初めに焼き始められ、のちに伊万里の港からヨーロッパへ輸出されました。幕末には、佐賀藩が西洋の工業技術をいち早く取り入れました。 |
| **Culture** | Pottery runs through the region's identity, from Arita and Imari porcelain to the earthier Karatsu ware prized in the tea ceremony. Karatsu is also known for its autumn Kunchi festival and its ornate floats. | 有田・伊万里の磁器から、茶の湯で愛される素朴な唐津焼まで、焼き物はこの地の個性そのものです。唐津は、豪華な曳山で知られる秋の唐津くんちでも有名です。 |
| ↳ Highlights | Karatsu ware | 唐津焼 |

*Region checks out; no findings. (Karatsu Kunchi is a recurring traditional festival, evergreen and in policy.)*

## 12. Nagasaki (`nagasaki`)

areaId `adf71b00-3d0d-4596-ae7d-b8064fc44b69` · 長崎県

| Field | English | 日本語 |
|---|---|---|
| Name | Nagasaki | 長崎 |
| Tagline | Japan's historic window to the world | 和華蘭の異国情緒 |
| **Specialties** | Nagasaki's kitchen reflects centuries of foreign contact. Champon and sara-udon layer noodles with seafood and vegetables, shippoku is a shared banquet blending Japanese, Chinese and Western dishes, and castella is a beloved sponge cake of Portuguese origin. | 長崎の食は、幾世紀にもわたる異国との交わりを映します。海鮮と野菜をのせたちゃんぽんや皿うどん、和華蘭の料理が並ぶ卓袱料理、そしてポルトガルに由来する銘菓カステラが親しまれています。 |
| ↳ Highlights | Champon · Castella cake | ちゃんぽん · カステラ |
| **Produce** | With its long coastline, Nagasaki is one of Japan's leading fishing prefectures. It is also the country's top grower of loquats, a sweet early-summer fruit. | 長い海岸線をもつ長崎は、日本有数の水産県です。初夏に実る甘い果実、びわの生産量でも全国一を誇ります。 |
| ↳ Highlights | Loquat (biwa) | びわ |
| **Attractions** | Nagasaki city gathers its layered history at Dejima, the former Dutch trading post, and at hillside sites like Glover Garden and Oura Church. Out on the Shimabara Peninsula, the Unzen volcano and the old castle town of Shimabara draw travellers to the region's hot springs and samurai streets. | 長崎の街は、かつてのオランダ商館跡である出島や、丘の上のグラバー園、大浦天主堂に、その重なり合う歴史を集めています。島原半島では、雲仙の火山と城下町・島原が、温泉や武家屋敷へと旅人を誘います。 |
| ↳ Highlights | Dejima · Unzen and Shimabara | 出島 · 雲仙・島原 |
| **History** | During Japan's period of seclusion, Nagasaki was the country's sole official window to Europe and China, with the Dutch confined to the island of Dejima. The city also carries the memory of the 1945 atomic bombing, remembered today at its Peace Park. | 鎖国の時代、長崎はヨーロッパと中国に開かれた唯一の公式の窓口であり、オランダ人は出島に限って居住を許されました。街はまた、一九四五年の原爆の記憶を、今日、平和公園に受け継いでいます。 |
| **Culture** | Long exposure to the outside world gave Nagasaki a distinctive blend of Japanese, Chinese and European influences, often called wakaran. That mix shows in its festivals, its churches, and the layout of its old quarters. | 長い異文化との接触は、長崎に和華蘭と呼ばれる独特の混じり合いをもたらしました。その趣は、祭りや教会、古い町並みのつくりに表れています。 |

*Note (finding 5): EN and JA taglines diverge in emphasis ("window to the world" vs "wakaran exotic ambience"). "Sole window to Europe and China" is correctly scoped.*

## 13. Miyazaki (`miyazaki`)

areaId `a544d213-2cce-4f66-b366-0b830319184c` · 宮崎県

| Field | English | 日本語 |
|---|---|---|
| Name | Miyazaki | 宮崎 |
| Tagline | Sun, surf and the land of myth | 日向路の神話と南国 |
| **Specialties** | Miyazaki's tables feature chicken nanban, fried chicken dressed with a sweet vinegar sauce and tartar, and sumibi-yaki, local chicken grilled over charcoal until smoky. Miyazaki beef is a prize-winning wagyu brand. | 宮崎の食卓には、甘酢とタルタルをまとった揚げ鶏のチキン南蛮や、地鶏を炭火でいぶし焼きにする炭火焼きが並びます。宮崎牛は、数々の賞に輝くブランド和牛です。 |
| ↳ Highlights | Chicken nanban · Charcoal-grilled chicken | チキン南蛮 · 地鶏の炭火焼き |
| **Produce** | The warm, sunny climate makes Miyazaki a major producer of mango, along with the Hyuganatsu citrus and cucumbers. Long hours of sunshine are the backbone of its farming. | 温暖で日照に恵まれた気候は、宮崎をマンゴーの一大産地とし、日向夏やきゅうりも多く育てます。豊かな日差しが、この地の農業を支えています。 |
| ↳ Highlights | Miyazaki mango · Hyuganatsu citrus | 宮崎マンゴー · 日向夏 |
| **Attractions** | Takachiho Gorge, a narrow canyon of columnar cliffs and a slender waterfall, is one of Kyushu's iconic landscapes. Along the coast, Aoshima island is ringed by wave-cut rock ledges known as the Devil's Washboard, and Udo Shrine sits in a seaside cave. | 柱状の断崖と細い滝が連なる高千穂峡は、九州を代表する景観のひとつです。海沿いでは、鬼の洗濯板と呼ばれる波状の岩棚に囲まれた青島や、海辺の岩窟に鎮座する鵜戸神宮があります。 |
| ↳ Highlights | Takachiho Gorge · Aoshima island | 高千穂峡 · 青島 |
| **History** | The old province of Hyuga is central to Japan's founding myths, including the descent of the heavenly grandchild at Takachiho. The Saitobaru burial mounds preserve one of the country's largest concentrations of ancient tombs. | 旧国名の日向は、高千穂への天孫降臨をはじめ、日本の建国神話の中心をなす地です。西都原古墳群には、国内でも有数の規模で古墳が集まっています。 |
| **Culture** | The mountains around Takachiho keep alive yokagura, all-night sacred dances that dramatise the myths of the gods. On the coast, Miyazaki's steady swell has made it one of Japan's best-known surfing regions. | 高千穂の山あいでは、神々の物語を演じる夜通しの神楽、夜神楽が受け継がれています。海辺では、安定した波が、宮崎を日本有数のサーフィンの地としています。 |
| ↳ Highlights | Takachiho yokagura | 高千穂の夜神楽 |

*Note (finding 14): EN tagline "surf" has no JA equivalent; optional.*

## 14. Kagoshima (`kagoshima`)

areaId `76c6eba7-0534-4e8d-81e9-7566486fa175` · 鹿児島県

| Field | English | 日本語 |
|---|---|---|
| Name | Kagoshima | 鹿児島 |
| Tagline | Volcano bay and the deep south | 桜島と薩摩の南国 |
| **Specialties** | Kagoshima is famous for kurobuta, its black Berkshire pork, and for satsuma-age, deep-fried fish cakes. Sweet-potato shochu is the everyday spirit, distilled all across the prefecture. | 鹿児島は、黒豚と、揚げた魚のすり身であるさつま揚げで知られています。芋焼酎は日常の酒で、県内各地で造られています。 |
| ↳ Highlights | Kurobuta pork · Satsuma-age fish cakes · Sweet-potato shochu | 黒豚 · さつま揚げ · 芋焼酎 |
| **Produce** | The volcanic soil is ideal for the satsuma-imo sweet potato, and Kagoshima is a top producer of green tea. It is also known for oddities of scale like the giant Sakurajima daikon and the tiny Sakurajima mikan. | 火山灰の土壌はさつまいもに適し、鹿児島は緑茶の主要な産地でもあります。世界一大きい桜島大根や、世界一小さい桜島小みかんといった、極端な作物でも知られています。 |
| ↳ Highlights | Satsuma sweet potato · Kagoshima tea | さつまいも · かごしま茶 |
| **Attractions** | Sakurajima, an active volcano rising straight out of the bay, looms over the city and often dusts it with ash. To the south, Ibusuki is famous for its natural sand baths, and offshore lie the cedar forests of Yakushima and the beaches of Tanegashima. | 湾から直接そびえ立つ活火山、桜島は、市街を見下ろし、しばしば灰を降らせます。南の指宿は天然の砂むし温泉で名高く、沖には屋久島の杉の森や種子島の浜が広がります。 |
| ↳ Highlights | Sakurajima volcano · Ibusuki sand baths | 桜島 · 指宿の砂むし温泉 |
| **History** | The Shimazu clan ruled Satsuma for roughly seven centuries from Kagoshima. In the 1800s the domain became a driving force behind the Meiji Restoration, producing several of modern Japan's founding leaders. | 島津氏は、鹿児島を拠点に約七百年にわたって薩摩を治めました。一八〇〇年代には、薩摩藩は明治維新の原動力となり、近代日本を築いた指導者を輩出しました。 |
| **Culture** | Satsuma craft traditions include Satsuma-yaki pottery and the delicate cut glass known as Satsuma Kiriko. A strong samurai heritage, along with the ever-present volcano, shapes the character of the region. | 薩摩の工芸には、薩摩焼や、繊細な切子細工である薩摩切子があります。武家の伝統と、間近にそびえる火山が、この地の気風を形づくっています。 |
| ↳ Highlights | Satsuma Kiriko cut glass | 薩摩切子 |

*Region checks out; no findings. (JA asserts "world's largest/smallest" for the Sakurajima daikon/mikan; both superlatives are verified.)*

---

## For the human owner

1. **Read the side-by-side above.** It is every published string in one place.
2. **Decide the flagged findings (3 to 16).** They are editorial or precision calls,
   not errors; leave or edit each in
   [`data/area_guides_curated.json`](../data/area_guides_curated.json).
3. **The two ✎ fixes (findings 1, 2)** are already in the curated JSON.
4. **To roll out any change**, run the publisher (a human step, do not automate):

   ```bash
   python publisher/publish_area_guides.py            # dry-run, proof the copy
   python publisher/publish_area_guides.py --commit    # bumps version, writes prod
   ```

   `_meta.reviewStatus` is `"reviewed"`, so `--commit` is not blocked. The
   `_meta.reviewNote` is kept honest: this is an agent-assisted verification, not
   independent third-party human sign-off.
