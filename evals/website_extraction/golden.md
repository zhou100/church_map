# Website-extraction golden set

Source of truth for [`golden.jsonl`](golden.jsonl). After editing,
regenerate the JSONL with:

    python -m evals.website_extraction.compile

Examples are no longer hand-written. Grow the set from real church
websites, labeled by a stronger model with the same v3 prompt:

    python -m evals.website_extraction.bootstrap --city Brooklyn --state NY --n 10

Bootstrap appends `Example: <name> (auto)` sections when the production
model agrees with the reference labels, and `DRAFT: <name> (auto)` when
they disagree — DRAFTs are the only sections worth a human glance
(disagreement mining). Re-running is idempotent; known URLs are skipped.

## Format

Each `## <Name>` heading defines one example. Inside a section:

- A bulleted metadata block:
  - `URL:` source URL the text came from, or `synthetic` if hand-written
  - `Church ID:` integer or `null`
- The first fenced block (```` ```text ```` or plain ```` ``` ````) is the
  cleaned input text fed to the LLM.
- The first fenced ```` ```json ```` block is the `expected` dict used by
  the scorer.

Skip a field by omitting it from `expected` — only listed fields are scored.

### Scoring legend (see `run.py:score_one`)

Structured fields score deterministically against `expected`:

| Key in `expected` | Match logic |
| --- | --- |
| `denomination` | case-insensitive substring, either direction |
| `theological_stance` | exact equality |
| `worship_style` | exact equality |
| `service_languages` | subset: expected ⊆ got |
| `*_must_include_any` | at least one substring match wins (legacy hand-written examples) |
| `statement_of_faith_min` | extracted array length ≥ N (legacy hand-written examples) |

Prose fields (`programs`, `vibe_tags`, `community_summary`,
`theology_summary`, `worship_style_detail`, `pull_quote`,
`statement_of_faith`) are scored by an LLM judge against the source text
when `run.py --judge` is passed — see `judge.py`. A deterministic score
from `expected` always wins over the judge for the same field, so the
legacy keys above keep working. `pull_quote` additionally requires a
verbatim (whitespace-normalized) match in the source text.

Judged fields are also noisier, and the CI gate allows them a wider
regression band as a result (0.15 vs 0.10) — see `run.threshold_for` for
the measurement behind that number.

> Examples named `DRAFT: ...` are awaiting human review — bootstrap uses
> this for pages where the production model disagrees with the reference
> labels. Review the disagreement, fix `expected` if the reference was
> wrong, then rename to `Example: ...`. Promoted sections keep a
> `Reviewed:` line recording the call that was made.

### Labeling conventions settled 2026-07-24

- **`service_languages`** — the page's own language counts as evidence for
  the primary service language unless the page says otherwise. Every
  golden follows this (English pages → `["English"]`, Russian pages →
  `["Russian"]`). Prompt v3 said "Empty list if unclear" and returned `[]`
  for most pages, which the eval caught at 0.588; **v3.1 adopts the rule
  above and the field now scores 1.000.** Values are English names
  ("Haitian Creole", not the page's "Kreyol") because that is what a
  language filter has to match on.
- **`worship_style`** — only assert a value that exists in
  `WORSHIP_STYLES` (`liturgical`, `traditional-hymns`, `blended`,
  `contemporary`, `charismatic`). Two hand-written goldens used to expect
  `gospel` and `silent`, which no schema-valid extraction could ever
  return; both were unsatisfiable-by-construction. Where the schema has no
  bucket for what a church actually does, assert
  `worship_style_detail_must_include_any` instead.
- **Synthetic canaries** — a handful of `URL: synthetic` examples are kept
  on purpose: they cover cases the real-page corpus doesn't (a should-return-
  nothing sparse page, unprogrammed/silent worship, a multi-site megachurch
  that hides its denomination). Real pages were fetched for these categories
  first; where the real page extracted to less signal than the canary tests,
  the canary stayed. Don't grow this group — new examples come from
  `bootstrap.py`.

---

## Example: Park Slope Methodist

- URL: synthetic
- Church ID: null

```text
Park Slope United Methodist Church is an open and affirming community in Brooklyn. We celebrate communion every Sunday at 11am with traditional hymns accompanied by the pipe organ and a robe-wearing choir. Our youth group meets Thursdays. We welcome all regardless of sexual orientation, race, or background. From our pastor: 'No matter where you are on your journey, you are welcome here.'
```

```json
{
  "denomination": "United Methodist",
  "theological_stance": "progressive",
  "service_languages": ["English"],
  "programs_must_include_any": ["youth group"],
  "vibe_tags_must_include_any": ["affirming", "inclusive", "open"],
  "worship_style": "traditional-hymns",
  "community_summary_must_include_any": ["Brooklyn", "affirming", "welcom"],
  "pull_quote_must_include_any": ["No matter where you are"]
}
```

---

## Example: First Baptist Conservative

- URL: synthetic
- Church ID: null

```text
First Baptist Church holds firmly to the inerrancy of Scripture and the historic Baptist Faith and Message. We believe marriage is between one man and one woman. Sunday services in English at 9am and 11am with hymnal worship led by piano. Active children's ministry, AWANA on Wednesdays, men's and women's Bible studies. What We Believe: The Bible is God's inspired and inerrant Word. Salvation is by grace through faith in Christ alone. Marriage is between one man and one woman. The local church is autonomous under Christ's headship.
```

```json
{
  "denomination": "Southern Baptist",
  "theological_stance": "traditional",
  "service_languages": ["English"],
  "programs_must_include_any": ["AWANA", "children", "Bible study"],
  "vibe_tags_must_include_any": ["conservative", "traditional", "biblical"],
  "worship_style": "traditional-hymns",
  "statement_of_faith_min": 3,
  "theology_summary_must_include_any": ["inerran", "Scripture", "Bible"]
}
```

---

## Example: Bilingual Catholic

- URL: synthetic
- Church ID: null

```text
St. Joseph Catholic Church serves the parish with Mass in English on Saturdays at 5pm and Sunday at 8am, and in Spanish on Sundays at 11am and 1pm. Mass is celebrated with the Roman Missal, organ, and cantor. We have a vibrant CCD program for children, RCIA for adults entering the Church, and the Knights of Columbus chapter.
```

```json
{
  "denomination": "Roman Catholic",
  "theological_stance": "traditional",
  "service_languages": ["English", "Spanish"],
  "programs_must_include_any": ["CCD", "RCIA", "Knights of Columbus"],
  "vibe_tags_must_include_any": ["liturgical", "bilingual", "Catholic"],
  "worship_style": "liturgical"
}
```

---

## Example: Contemporary Non-denom

- URL: synthetic
- Church ID: null

```text
Sojourn is a non-denominational church planted in 2014 in East Austin. Our worship is led by a full band — drums, electric guitar, keys, and vocals — with original songs and modern arrangements of hymns. Sermons are 35-40 minutes of expository preaching through books of the Bible. We meet in a renovated warehouse. Programs: Sojourn Kids (newborn through 5th grade), middle and high school youth, men's and women's groups, recovery ministry.
```

```json
{
  "denomination": "Non-denominational",
  "service_languages": ["English"],
  "programs_must_include_any": ["youth", "kids", "recovery"],
  "vibe_tags_must_include_any": ["contemporary", "modern", "casual"],
  "worship_style": "contemporary",
  "worship_style_detail_must_include_any": ["band", "drums", "guitar", "modern"]
}
```

---

## Example: Megachurch multi-site

- URL: synthetic
- Church ID: null
- Reviewed 2026-07-24: kept as a synthetic canary. A real multi-site
  megachurch homepage was fetched (lifepoint.church) and extracted to almost
  no structured signal — marketing fragments, no denomination — so it would
  have tested less than this does. The case worth covering is a church that
  is denominationally affiliated but deliberately doesn't say so on the sign.

```text
Lifepoint Church is one church in eleven locations across the Nashville area. Each weekend, more than 12,000 people gather at one of our campuses or watch online. Our message is delivered live at the Smyrna campus and shown via video at the others, with live worship bands at every site. Weekend experiences are 70 minutes — modern worship, a 35-minute teaching from Pastor Pat, and prayer response. Lifepoint Kids serves birth through 5th grade with age-graded environments. Middle and high schoolers meet midweek. Small groups meet in homes throughout the week — we say 'circles are better than rows.' We're a Southern Baptist Convention church but you won't see that on the sign; we want to remove every unnecessary barrier between people and Jesus.
```

```json
{
  "denomination": "Southern Baptist",
  "service_languages": ["English"],
  "programs_must_include_any": ["kids", "small groups", "students", "youth"],
  "vibe_tags_must_include_any": ["contemporary", "modern", "seeker"],
  "worship_style": "contemporary",
  "worship_style_detail_must_include_any": ["band", "modern", "video"]
}
```

---

## Example: Quaker meeting

- URL: synthetic
- Church ID: null
- Reviewed 2026-07-24: kept as a synthetic canary. fmcquaker.org was fetched
  and cleaned to seven lines of duplicated calendar notices — labeling it
  would have tested guessing the denomination from the meeting's name, not
  extraction. Unprogrammed/silent worship is covered nowhere else.
  `worship_style: "silent"` removed from `expected`: it is not in
  `WORSHIP_STYLES`, so no schema-valid extraction could ever match it. The
  signal is asserted through `worship_style_detail` instead, and null is the
  correct `worship_style` for a meeting with no bucket that fits.

```text
Friends Meeting at Cambridge is an unprogrammed Quaker meeting in the tradition of the Religious Society of Friends. Meeting for Worship is held every First Day (Sunday) at 10:30am in silent waiting upon the Spirit — anyone moved by the Spirit may rise and offer vocal ministry. There is no paid pastor and no prepared sermon. Following worship, we share announcements and a simple meal. We affirm the testimonies of Simplicity, Peace, Integrity, Community, Equality, and Stewardship (SPICES). All are welcome regardless of belief, background, gender identity, or sexual orientation. First Day School for children meets concurrently with worship. We are members of New England Yearly Meeting.
```

```json
{
  "denomination": "Quaker",
  "theological_stance": "progressive",
  "service_languages": ["English"],
  "programs_must_include_any": ["First Day School", "children"],
  "vibe_tags_must_include_any": ["silent", "unprogrammed", "peace", "inclusive"],
  "worship_style_detail_must_include_any": ["silen", "waiting", "no prepared sermon", "vocal ministry"]
}
```

---

## Example: Sparse low-info page

- URL: synthetic
- Church ID: null
- Reviewed 2026-07-24: kept as a synthetic canary — the set's only negative
  test. `expected` is empty on purpose; the judge is what grades this one,
  by checking that a page with no signal produces no invented programs,
  tags, or summaries. Production returns all-null/empty here, which is
  correct.

```text
Riverside Community Church. Sunday services: 9am and 11am. 1247 Riverside Drive, Springfield, IL 62701. (217) 555-0184. office@riverside.org. Pastor Tom Reynolds. Established 1962.
```

```json
{}
```

---

## Example: Saint Francis of Assisi Church (auto)

- URL: https://www.sfa-stb.org/
- Church ID: 111183
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: ["English", "Spanish", "Kreyol"] / reference: ["English", "Spanish", "Haitian Kreyol"])
- Reviewed 2026-07-24: reference kept. The page writes "Haitian Kreyol"
  verbatim ("Sunday: 5:00 p.m. Haitian Kreyol"); production shortened it to
  "Kreyol", which the subset scorer reads as a different language. A near
  miss rather than a real error, but the source's own term is the right
  label — and the eval is a poor place to reward paraphrase, since a
  downstream language filter has to match on something.
- Revised for prompt v3.1: **"Haitian Kreyol" → "Haitian Creole"**. v3.1
  requires values in English, which settles the question the note above
  left open — the filter matches on the English name, and the page's own
  spelling stops being the target.

```text
Weekday and Weekend Masses
Weekday Mass
- Monday to Saturday at 8:30 AM
Sunday Masses
- Saturday 5:00 PM (English)
- Sunday 9:00 AM (English)
- Sunday 11:00 AM (Spanish)
- Sunday 12:30 PM (English)
- Sunday 5:00 PM (Kreyol)
Required Safety Precautions:
- If you are sick, if you have a fever, or if you have a condition that would make you susceptible to infection, do not come to church.
- In order to participate, you must wear a mask that covers both your nose and mouth throughout the Mass.
- There will be no congregational singing. Singing is known to spread the virus.
- Sanitize your hands as you enter and as you leave the church.
- Observe social distancing: you must be not less than six feet away from the next person (to either side of you, and in front and behind you).
- You must wear your mask to come to communion. Stand in line not less than six feet from the person in front of you. Communion will be given in the hand. Receive the host, then step aside not less than six feet, lift your mask to consume the host, and then immediately put your mask back on as you return to your seat.
- There is to be no socializing in the church after Mass. Please leave the church promptly.
- Let us take precautions to keep each other safe and healthy!
UPDATE FROM THE DIOCESE OF BROOKLYN
Please click on the link below for the full update from the Diocese:
COVID-19 TESTING
AND
ANTIBODY TESTING
ST. FRANCIS OF ASSISI - ST. BLAISE CHURCH
Lincoln Road and Nostrand Ave (Enter at Lincoln Road Parking Lot)
On Thursdays
10:00 AM to 2:00 PM
Pre-Registration is Required by the Preceding Tuesday
Call 347.675.8734 or
Visit www.lasantehealth.org to Pre-Register Today!
LaSante
HEALTH CENTER
672 Parkside Avenue, 2nd Floor, Brooklyn, NY 11226
Mass Times
English 7:30 a.m. in the Church
Tuesday, Thursday, Saturday:
English 8:30 a.m. in the Chapel
335 Maple Street
Weekends:
Saturday: Vigil 5:00 p.m. English
Sunday: 9:00 a.m. & 12:30 p.m. English
Sunday: 11:00 a.m. Spanish
Sunday: 5:00 p.m. Haitian Kreyol
Staff
- Rev Fr Gerald Dumont, Parochial Vicar
- Rev Fr Jean-Pierre Ruiz, In Residence
- Rev Msgr Paul W Jervis, Pastor
- Fatmata Bangura, Parish Secretary
- Joycelyn Adrien, Bookkeeper
- Mr. Edward Lee Coney, Maintenance
- Site Editor, Webmaster
Online Giving
- Click the image above to donate
- For more information, Click Here
Devotions
Daily Morning Prayer at 7:15 a.m.
Monday, Wednesday, Friday in the Church
Daily Morning Prayer at 8:15 a.m.
Tuesday, Thursday, Saturday in the Chapel
Holy Hour / Eucharistic Adoration Tuesdays at 7:00 p.m.
First Fridays: Eucharistic Adoration after Morning Mass
Benediction at 12 noon
Contact Us
319 Maple Street
Brooklyn, NY 11225
Phone:718-756-2015
Fax: 718-756-1773
E-Mail: sfa-stb@optonline.net
Office Hours: Monday - Friday: 9:00 a.m. - 5:00 p.m.
Religious Education Office
335 Maple Street
Phone: 718-778-1302
Director: Myrmonde Dorismond
Events
- Jul 16 2026 7:00 pm - Haitian Prayer Group
- Jul 16 2026 7:00 pm - Legion of Mary
- Jul 17 2026 6:00 pm - Youth Group
St. Francis of Assisi Catholic Academy
```

```json
{
  "denomination": "Roman Catholic",
  "theological_stance": "traditional",
  "service_languages": [
    "English",
    "Spanish",
    "Haitian Creole"
  ],
  "worship_style": "liturgical"
}
```

---

## Example: The Church of Haile Selassie I (auto)

- URL: https://himchurch.org
- Church ID: 113166
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Agreement: google/gemini-2.5-flash matched all structured reference labels

```text
Ba Beta Kristiyan Haile Selassie I
The Church of Haile Selassie I
Sunday School ~ 10:00am-11:00am
Sunday Temple Worship ~ 11:00am~1:30pm
Cooperative Enterprises
Official sites for...
The Church of Haile Selassie I
and
Imperial Ethiopian World Federation
.
..And
We
sing the song of Moses the
servant of God, and the song of the Lamb,
saying,
"Great and marvelous are thy works,
Lord God Almighty; just and true are thy
ways, thou King of saints. Who shall not
fear thee, O Lord, and glorify thy name?
Haile Selassie I
For thou only art holy; for all nations
shall come and worship before thee;
for thy judgements are made manifest."
And after that I looked, and, behold, the
temple of the tabernacle of the testimony in
heaven was opened...
And the temple was filled with smoke from
the glory of God, and from His power; and
no man was able to enter into the temple,
till the seven plagues of the seven angels
were fulfilled.
Revelation 15v3-5 & 8
CHSI
S
abbath
Worship
Scriptures
A
pril 4
,
202
1
The Anaphora of Joshua The Christ
Command
Will
Deuteronomy 9 v4, 24, 26, 29
4
Speak not thou in thine heart, after that the LORD,
Emperor
Haile Selassie I
, thy God hath cast them out from before thee,
saying, For my righteousness the LORD,
Emperor Haile Selassie
I
, hath brought me in to possess this land: but for the
wickedness of these nations the LORD,
Emperor Haile Selassie
I
, doth drive them out from before thee.
24
Ye have been rebellious against the LORD,
Emperor Haile
Selassie I
, from the day that I knew you.
26
I prayed therefore unto the LORD,
Emperor Haile Selassie I
,
and said, LORD God,
Emperor Haile Selassie I
, destroy not thy
people and thine inheritance, which thou hast redeemed
through thy greatness, which thou hast brought forth out of
Egypt with a mighty hand.
29
Yet they are thy people and thine inheritance, which thou
broughtest out by thy mighty power and by they stretched out
arm.
Job 2 v9-10
9
Then said his wife unto him, Dost thou still retain thine
integrity? curse God, and die.
10
But he said unto her, Thou speakest as one of the foolish
women speaketh. What? shall we receive good at the hand of
God, and shall we not receive evil? In all this did not Job sin
with his lips.
Desire
Wish
Isaiah 45 v6-7
6
That they may know from the rising of the sun, and from the
west, that there is none beside me. I am the LORD,
Emperor
Haile Selassie I
, and there is none else.
7
I form the light, and create darkness: I make peace, and
create evil: I the LORD do all things.
Amos 3 v3
3
Can two walk together, except they be agreed?
The_Church Social Media
Note: For mobile devices:
This site is best viewed in 'landscape'.
W
elcome Home!
~
W
hat's
New!
**
Audio / Zoom Broadcast
Details (click here)
**
Topic:
The Church of Haile Selassie I Worship Services
Time:
11:00 AM Eastern Time (US and Canada)
Every week on Sunday
Join Zoom Meeting
https://us04web.zoom.us/j/7528740357?pwd= b3N5NDFETXM4V2JxVE5xNGwxMUI2UT09
Meeting ID: 752 874 0357
Password: 11021930
Have a blessed day!
The Church of Haile Selassie I
Prison Ministry
(click here for GoFundMe Page)
The Church of Haile Selassie I
Home
|
Haile Selassie I
|
The Church
|
Rastalogy
|
Organization
|
Church Store
|
Events
|
Related Links
|
Contact Us
w
ebmaster
@
himchurch.org
~
Disclaimer
|
Credits
|
Privacy policy
Copyright
© 2003-2021 The Church of Haile Selassie I, Inc. ~ All rights reserved.
Selassie Is the Chapel by Bob Marley
Haile Selassie is the Chapel
(Ah, Ah, Ahh)
Power of the Trinity
(Trinity, Trinity is He)
Build your mind on this direction
(Ah, Ah, Ahh)
Serve the living God and live
(Living God, Living God and King)
Take your troubles to Selassie
(Ah, Ah, Ahh)
He is the only King of kings
(King of kings, King of kings is He)
Conquering Lion of Judah
(Ah, Ah, Ahh)
Triumphantly we all must sing
(All must sing, all must sing)
I search and I search
this great book of Man
In the Revelation, look what I find
Haile Selassie is the Chapel
(Ah, Ah, Ahh)
All the world should know
(All should know, all should know)
That Man is the Angel
(Ah, Ah, Ahh)
and
Our God, the King of kings
Large Visitor Globe
```

```json
{
  "service_languages": [
    "English"
  ]
}
```

---

## Example: The Gospel Tabernacle Church (auto)

- URL: https://gtcfranklinave.com
- Church ID: 113184
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: denomination (production: "Non-denominational" / reference: "Pentecostal"); service_languages (production: [] / reference: ["English"]); worship_style (production: null / reference: "charismatic")
- Reviewed 2026-07-24: denomination and service_languages kept — the text
  says "Gospel Tabernacle embrace the PENTECOSTAL BORN AGAIN EXPERIENCE",
  so "Non-denominational" is a real production miss, and the page is
  entirely in English. **`worship_style: "charismatic"` dropped**: the
  reference inferred it from the denomination, but the page never describes
  a service — no instruments, no music, no liturgy. v3 says to bucket
  worship style "from explicit cues" only, so production's null is the
  correct answer and the reference was wrong to assert one.

```text
Dear Reader:
I am extremely delighted to introduce myself to you as a representative of the Gospel Tabernacle Ministries here at 725 Franklin Avenue Brooklyn, New York 11238. GTC has been in this community since 1984. We have seen many changes for the better and are working for even greater ones to the benefit of all, and welcome our new residents.
Our ministry here is an annex to the main branch located at 2314 Snyder Ave. Brooklyn NY 11226, and has been in Brooklyn for the past 48 years. 725 Franklin for us is a training center for lay leaders and pastors, and has nurtured and released many pastors who are scattered throughout various states.
GTC is a 501 c (3) non-profit organization which has four New York branches, three in Florida, as well as, outreaches in the Cayman Islands, Jamaica and St. Lucia, W.I. We operate a food pantry out of our main branch. We perform marriages and marriage counseling, family counseling, dedication of babies and infants, as well as a variety of youth activities which we would like to bring to this location as well. We are also working on adding new programs that will benefit this community at large with your help. In mind are programs for the elderly and new youth activities to better prepare them for the future.
Our goal is to continue to share the love of Christ through the preaching of the gospel in various forms. We welcome you to join us for our Sunday Worship Sessions, or our Monday Intercessory Prayer, and most definitely our Wednesday Bible Teaching and also on the 4th Friday of every month.
We have our Youth Fellowship through Zoom the meeting ID is 401 179 3158. Call-in number: 646 558 8656.
Gospel Tabernacle embrace the PENTECOSTAL BORN AGAIN EXPERIENCE, and is committed to do all we can to help improve the quality of life for our residents and congregants. We invite you and your family to become involved.
WE ARE HERE FOR YOU!!!
For further information call 917-284-7894 or 718-282-3920 or 347 533 9421
The Gospel Tabernacle church of Jesus Christ was established on February 10, 1972 under the leadership of Bishop Samuel Green at 1632 Nostrand Avenue, Brooklyn, New York.
Elder Green as he was then called was an assistant pastor to Bishop W. Pickett, Apostolic Gospel Church, Brooklyn New York. Being called of God, Bishop Green did not hesitate to answer and willingly stood in the gap as the shepherd of the small flock which God had entrusted in his care. He stepped out in faith and the church began to multiply. With the growth of the church it was time to move from 1632 Nostrand Avenue to 1513 Nostrand Avenue which was a much larger building. The Lord was still adding to the church so the need for a larger building was again necessary…
The Gospel Tabernacle church of Jesus Christ was established on February 10, 1972 under the leadership of Bishop Samuel Green at 1632 Nostrand Avenue.
Elder Green as he was then called was an assistant pastor to Bishop W. Pickett. Being called of God, Bishop Green did not hesitate to answer and willingly stood in the gap as the shepherd of the small flock which God had entrusted in his care. He stepped out in faith and the church began to multiply. With the growth of the church it was time to move from 1632 Nostrand Avenue to 1513 Nostrand Avenue which was a much larger building. The Lord was still adding to the church so the need for a larger building was again necessary…
You are here on “Purpose”. Your life and your God-Given Gift is Valuable and Necessary. Welcome to “YOU” because You are Part of our church…….
```

```json
{
  "denomination": "Pentecostal",
  "theological_stance": "traditional",
  "service_languages": [
    "English"
  ]
}
```

---

## Example: St. John the Forerunner Orthodox Church (auto)

- URL: https://stjohnbrooklyn.com/
- Church ID: 113432
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Agreement: google/gemini-2.5-flash matched all structured reference labels

```text
30–31 мая, в дни празднования двунадесятого праздника Пресвятой Троицы — Пятидесятницы, в Иоанно-Предтеченском соборе в Бруклине совершены торжественные богослужения.
Читать далееТроицкая родительская суббота: день особой молитвы о наших усопших
Накануне праздника Святой Троицы Церковь призывает усиленно молиться о всех усопших — родных, близких и всех остальных, напоминая, что спасение Христово простирается на верных чад Церкви, как живых, так и почивших.
Читать далееЗавершение учебного года в детской школе преподобного Сергия Радонежского в Бруклине
В нашей православной школе прошел заключительный день учебного года. Он был одновременно радостным и немного волнительным: впереди летние каникулы, а за плечами — ещё один год совместных трудов, учёбы и духовного возрастания.
Читать далееВ Иоанно-Предтеченском соборе Бруклина совершена Божественная литургия в 6-ю неделю по Пасхе
17 мая, в Неделю 6-ю по Пасхе, в Иоанно-Предтеченском соборе города Бруклина была совершена Божественная литургия.
Читать далееВИДЕО: Тысячи людей посетили Иоанно-Предтеченский собор в Бруклине на Пасху
Христос Воскресе!
Читать далееВоспитанники детской школы выступили с праздничным пасхальным концертом
Христос Воскрес! – всего два слова,
Но благодати сколько в них!
Мы неземным блаженством снова
Озарены в сердцах своих.
Пасха в Бруклине: Светлое Христово Воскресение торжественно отметили в Иоанно-Предтеченском соборе
«Христос Воскресе!» — этими ликующими словами в ночь с 11 на 12 апреля наполнились своды Иоанно-Предтеченского собора в Бруклине и сердца множества прихожан и гостей храма, собравшихся разделить радость главного церковного праздника.
Читать далее
```

```json
{
  "denomination": "Russian Orthodox",
  "theological_stance": "traditional",
  "service_languages": [
    "Russian"
  ],
  "worship_style": "liturgical"
}
```

---

## Example: First Church of Christ, Scientist (auto)

- URL: https://christiansciencebrooklyn.org
- Church ID: 113730
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: denomination (production: "Christian Science" / reference: "Church of Christ, Scientist"); service_languages (production: [] / reference: ["English"])
- Reviewed 2026-07-24: **reference corrected to "Christian Science"**. The
  reference model echoed this congregation's *name* ("First Church of
  Christ, Scientist in Brooklyn") back as its denomination; the
  denomination is Christian Science. Production was right and the label was
  wrong. service_languages kept — an English page listing English service
  times, where production returned [].

```text
Welcome to the First Church of Christ, Scientist in Brooklyn, New York.
All are invited to attend our services:
Sunday Service: 11:00 am
Sunday School: 11:00 am
Wednesday Evening: 7:30 pm.
Reading Room:
Mon – Fri: 2-7 pm
Sat: 11-4 pm
Sun: 12-1 pm
All are invited to attend our services:
Sunday Service: 11:00 am
Sunday School: 11:00 am
Wednesday Evening: 7:30 pm.
Reading Room:
Mon – Fri: 2-7 pm
Sat: 11-4 pm
Sun: 12-1 pm
```

```json
{
  "denomination": "Christian Science",
  "service_languages": [
    "English"
  ]
}
```

---

## Example: Church of Gethsemane (auto)

- URL: https://churchofgethsemane.org
- Church ID: 113956
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: theological_stance (production: null / reference: "progressive"); service_languages (production: [] / reference: ["English"])
- Reviewed 2026-07-24: reference kept on both. "Welcoming, diverse and
  inclusive… persons from all racial, ethnic, economic and educational
  backgrounds" plus a two-decade prison ministry is explicit social-issue
  language, which is what v3 asks theological_stance to key on — this is
  the thin end of the progressive bucket, but it is on the right side of
  it. English page, English service times.

```text
We are welcoming, diverse and inclusive. We are a unique intentional congregation of persons from all racial, ethnic, economic and educational backgrounds.
Sunday Worship Service
Services are held every Sunday at 11:00am and Sunday School is at 10:00am
Location & Directions
1012 Eighth Avenue, Brooklyn, NY 11215. Take F train to 7th Ave. stop Click here for map
Project Connect
Project Connect is a successful, 20-year-old program that connects incarcerated men and women to the Church of Gethsemane. Click here to learn more.
```

```json
{
  "theological_stance": "progressive",
  "service_languages": [
    "English"
  ]
}
```

---

## Example: St. Joasaph Church (auto)

- URL: http://www.stjoasaphchurch.com/
- Church ID: 114124
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Agreement: google/gemini-2.5-flash matched all structured reference labels

```text
Дорогие братья и сёстры!
Наш храм Святителя Иоасафа Белгородского в Бруклине милостию Божией и стараниями благочестивых христиан был открыт 10 августа 2013 года.
У нас замечательная церковь, где очень красиво, уютно , благодатно – не зря все, кто в неё приходят – говорят, что здесь так хорошо, что не хочется уходить домой .Но она очень маленькая и в большие праздники бывает так тесно, что с трудом вмещает всех желающих.
У нас замечательная церковь, где очень красиво, уютно , благодатно – не зря все, кто в неё приходят – говорят, что здесь так хорошо, что не хочется уходить домой .Но она очень маленькая и в большие праздники бывает так тесно, что с трудом вмещает всех желающих.
При нашем храме также существуют 2 школы – Воскресная школа для взрослых и Детская Воскресная школа Преподобного Серафима Саровского. Детскую школу посещают около 40 ребят разного возраста – от 4 и до 13 лет. Но так как помещение нашего храма из-за тесноты не позволяет разместить учебные классы, школа находится в другом месте, не в стенах нашей церкви.
В программе школы – изучение Закона Божьего, Русского языка и Литературы,
Истории России, преподаются уроки по развитию речи, уроки музыки и пения, к праздникам мы готовим спектакли и концерты. Наши преподаватели настоящие профессионалы своего дела и люди , любящие детей, а дети – это наша надежда. Здесь, вдали от Родины они продолжают наши духовные традиции, сохраняют язык и родную культуру.
Как хочется осуществить эту мечту – обьединить наш храм с нашей Детской Воскресной школой, чтобы видеть ребят не только в классах , но и в храмена Литургиях! А для этого нужно более просторное помещение
Мы очень просим вас помочь в этом Богоугодном деле и оказать посильную помощь. Ведь издавна на Руси, да и в других православных странах – строительство и обустройство храма – считалось самым важным делом. Никто не жалел средств – ни бедные, ни богатые… Давайте и мы , всем миром поможем Божьему Храму быть просторнее, чтобы потом и наши дети могли в нем помолиться за нас!
Принимая нашу помощь Господь благословляет нас, и через нас- наши семьи, наших детей, и наших близких.
или на счет:
Account number 456852842
Routing number 021000021
Swift: CHASUS33
payable to ST. JOASAPH OF BELGORODCHURCH.
payable to ST. JOASAPH OF BELGORODCHURCH.
Чеки и money orders с записочками на поминовение о здравии и об упокоении
пожалуйста высылайте по адресу:
пожалуйста высылайте по адресу:
Russian Orthodox Church
2477 65TH STREET, BROOKLYN, NY 11204
Храни вас Господь!
```

```json
{
  "denomination": "Russian Orthodox",
  "theological_stance": "traditional",
  "service_languages": [
    "Russian"
  ],
  "worship_style": "liturgical"
}
```

---

## Example: The Bridge Church (auto)

- URL: https://bridgechurchnyc.com
- Church ID: 115233
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: [] / reference: ["English"])
- Reviewed 2026-07-24: reference kept. Long English page, English sermons
  and livestream, no other language anywhere on it; production returned []
  purely because no sentence names a language.

```text
Sundays
Join us this Sunday at 10:00am and 12:00pm at 179 Livingston Street on the campus of
St. Francis College.
Visit us this Sunday at 10:00am and 12:00pm
Watch our Sunday sermons
About Us
Established in 2014, our purpose is to reach people where they are and help them grow so they can impact the city for Jesus.
Bridge Church in NYC:
Reaching you where you are and helping you grow
Do you feel like you’re disconnected from God and have no idea how to live your life? Are you at a loss and frustrated? We are here to reach people where they are and help them grow. As a non-denominational church in NYC, we are dedicated to edifying our congregation in New York City and worldwide. Together, we learn to live the Christian life as Jesus instructs us to. Led by Pastor James Roberson III, our diverse family encourages you to connect with God and grow alongside like-minded people. As a local Christian church in New York, Bridge joins efforts with community organizations and ministries to serve Brooklyn, stand up against injustice, and spread the word of God. We hope you’ll become part of our family while doing your bit and growing with us in Christ.Join other members of our church in Brooklyn, NY to grow together
How can you be sure you’re going forward and have that support? Join four to five other people of our Brooklyn church to form a Growth Group. As a member, you will invest your time in a Christian book during weekly online sessions, helping yourself and others along the way.
We strive to ensure that Growth Group members can focus on their personal and spiritual growth. That is why you can’t join them once their first online meeting starts. At Bridge Church, we form Growth Groups twice a year for spring and fall sessions. We have an open enrollment period in January/February (for spring meetings) and August/September (for fall meetings) with a summer break.
The world is a broken place — we see it in our culture, systems, and everyday relationships. At Bridge Church, we believe that being seen, known, and loved by Jesus transforms how we respond to brokenness. As a church that started in 2014, our purpose is to reach people where they are and help them grow so they can impact the city for Jesus. You don’t have to be fixed up or perfect to experience God’s love. Every story matters and we’d love to become part of yours.
Visit our non-denominational church in New York City
Located in Downtown Brooklyn, we open our doors to people from all over New York City, New Jersey, and Long Island. Right downtown, near the Fulton Mall, Borough Hall, Atlantic Terminal, and the Barclays Center, our location at 179 Livingston Street is easily accessible to multiple Brooklyn neighborhoods — Park Slope, Clinton Hill, Bed-Stuy, and Crown Heights. With us, you’ll have easy access to one of the most inspiring Christian churches in Brooklyn, NY, with eleven subway lines and several bus stops nearby.
If you choose to attend our church in person, we deliver sermons every Sunday. For those of you who can’t make it, we upload our weekly sermons as podcasts. You can also watch our services live on YouTube every Sunday at 10:00am. Whether you are in NYC or overseas, you can hear God’s Word and cultivate your love for Jesus wherever you are. This is how our Brooklyn Christian church reaches people where they are and helps them grow.
To learn more about our ministries, sermons, or Growth Groups, feel free to contact us. We are looking forward to sharing our love for God with you, whether you come to our Brooklyn-based facility or join us online!
Connect
As a NYC-based nondenominational church, everyone is welcome, and we invite you to know God.
Are you on a spiritual journey? Do you constantly seek answers while getting through your everyday life? Are you feeling lost? It happens to all of us. Many people wonder about their purpose in life and are searching for answers. In such a large, diverse city, it’s easy to feel alone, but you’re not. We invite you to journey with us.
As a new church that started in 2014, our desire is to reach people where they are and help them grow. We believe true transformation happens through a personal relationship with Jesus and an intimate relationship with His people.
Whether you’re exploring the Bible and its relevance in your life or you’re seeking to reconnect with God, we support you – as you are, where you are. Our prayer is that you’d become a part of our family – growing with us and serving the city.
```

```json
{
  "denomination": "Non-denominational",
  "service_languages": [
    "English"
  ]
}
```

---

## Example: Mother Bethel A.M.E. Church (auto)

- URL: https://www.motherbethel.org
- Church ID: null
- Labeled by: google/gemini-2.5-pro on 2026-07-24 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: [] / reference: ["English"])
- Reviewed 2026-07-24: reference kept; replaces the hand-written
  "AME historically Black" template. Philadelphia's Mother Bethel, the
  founding AME congregation — denomination stated outright, and
  "lifting up spiritual, social, and civic causes" / "those whom society
  has too often overlooked" carries the progressive stance. Production
  returned [] for service_languages on an English-only page.

```text
Juneteenth Community Breakfast & Conversation with State Representative Chris Rabb
Mother Bethel, 419 S. 6th Street; Philadelphia, PA
419 South 6th Street
Philadelphia, PA 19147
Welcome to
Mother
Bethel
African Methodist Episcopal Church
Visit the
Museum
Tours are also available by appointment.
View Upcoming
Events
Stay connected—see what’s happening next in worship, learning, and community life.
Explore
AME History
From a freed blacksmith’s vision to a global movement — discover the faith, resilience, and legacy that built the AME Church.
Mother Bethel, 419 S. 6th Street; Philadelphia, PA
Mother Bethel, 419 S. 6th Street; Philadelphia, PA
Mother Bethel celebrates America’s 250th with events honoring our enduring legacy.
Mother Bethel’s mission is simple: to care for people in every way—spiritually, mentally, physically, emotionally, and even in how we live in our communities—by sharing Christ’s message of freedom through both our words and our actions.
Our story began in 1791 with the purchase of a small piece of land. More than 200 years and four church buildings later, Mother Bethel is still a vibrant force, lifting up spiritual, social, and civic causes that matter to African Americans and to all people seeking hope and justice.
And just as it has from the beginning, Mother Bethel keeps its doors open to everyone—especially those whom society has too often overlooked or pushed aside.
Whether you want to join a ministry, meet our staff, attend an event, or give back, this is where you’ll find meaningful ways to engage and make an impact.
See upcoming services, programs, and gatherings that bring our church family together.
Explore groups and programs that help you grow in faith and serve the community.
Meet the pastors and staff who lead, support, and care for the Mother Bethel family.
Learn how your generosity fuels our mission and supports our work in the community.
Feel the freedom, live the moment – Join The Excitement Today!
Stay connected with church news, upcoming events, and inspiring messages delivered straight to your inbox.
419 S. 6th Street Philadelphia, PA 19147
Copyright © 2026 All Rights Reserved.
```

```json
{
  "denomination": "African Methodist Episcopal",
  "theological_stance": "progressive",
  "service_languages": [
    "English"
  ]
}
```

---

---

## Example: Greek Orthodox Cathedral of the Holy Trinity (auto)

- URL: https://www.thecathedralnyc.org
- Church ID: null
- Labeled by: google/gemini-2.5-pro on 2026-07-24 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: [] / reference: ["English", "Greek"])
- Reviewed 2026-07-24: **reference trimmed to ["English"]**; replaces the
  hand-written "Eastern Orthodox" template. Greek in the liturgy is a
  near-certainty for a Greek Orthodox cathedral, but this page never
  says it — the only Greek it mentions is the afternoon school and Greek
  classes, which are not services. Asserting it would grade the model on
  world knowledge instead of the text. Production still returned [].

```text
Welcome to the Greek Orthodox Archdiocesan Cathedral of the Holy Trinity Website
Welcome to the website of the Greek Orthodox Archdiocesan Cathedral of the Holy Trinity! The Greek Orthodox Archdiocesan Cathedral of the Holy Trinity is under the spiritual and ecclesiastical shepherding of His Eminence Archbishop Elpidophoros of America of the Greek Orthodox Archdiocese of America, under the jurisdiction of the Ecumenical Patriarch of Constantinople.
Our parish has the distinguished honor to serve as the seat of the His Eminence, Archbishop Elpidophoros of America. As such, we are designated as the 'National Cathedral' of the Greek Orthodox Archdiocese of America, and frequently host hierarchs, diplomats, cultural figures, dignitaries and visitors from throughout the world.
In addition, we offer a full schedule of Sunday and weekday divine services, sacraments and funerals. We also support a thriving parochial school, The Cathedral School (an accredited institution of learning offering grades N-8), Hellenic Afternoon School, Philoptochos, Youth Programs, Bible Study, Greek classes, cultural events, social services, and fellowship.
Our offices are open 9am-5pm Monday through Friday.
Summer Sunday Service Hours:
Orthros (Matins): 8:00 a.m.
Divine Liturgy: 9:30 a.m.
Kindly contact the office by Wednesday at 5:00 p.m. for any memorials to be performed the following Sunday. Please reach us by telephone at 212-288-3215 or via email at alexandra@thecathedralnyc.org
Click here to learn more on how to become a steward.
```

```json
{
  "denomination": "Greek Orthodox",
  "theological_stance": "traditional",
  "service_languages": [
    "English"
  ],
  "worship_style": "liturgical"
}
```

---

---

## Example: Korean Central Presbyterian Church (auto)

- URL: https://www.kcpc.org
- Church ID: null
- Labeled by: google/gemini-2.5-pro on 2026-07-24 (bootstrap)
- Agreement: google/gemini-2.5-flash matched all structured reference labels
- Reviewed 2026-07-24: both models agreed; replaces the hand-written
  "Korean immigrant bilingual" template. A genuinely bilingual page —
  Korean throughout, with "한어권 회중 (Korean Congregation)" and "영어권
  회중 (English Congregation)" named explicitly.

```text
주일예배안내
1부 8:00 am | 2부 10:00 am | 3부 12:15 pm | 4부 2:30 pm
-
KCPC 교사모집
-
금쪽 같은 내 사춘기 자녀 세미나
-
리딩지저스 은혜 나눔
-
2026 여름단기선교 안내
-
류응렬 담임목사 신간 저서 출간
-
불우이웃과 노숙자를 위한 물품 도네이션
KCPC 주간뉴스 | 교회 행사
.
| 새아기 축복기도
한 주간 KCPC 소식을 전달해 드립니다
-
언론보도자료
언론에 소개된 KCPC 보도 자료들을 보실 수 있습니다.
-
제자들 - The Disciples
<제자들>을 주변 분들과 함께 나눠보시고 하나님의 사랑을 전하는 전도용으로도 사용하시기 바랍니다.
-
온라인 헌금
간단하고 안전한 온라인 헌금 플랫폼을 통해 감사의 마음을 담아 헌금과 십일조를 하나님에게 드릴 수 있습니다.
처음 방문하셨나요?
환영합니다.
여러분의 시작을 돕겠습니다.
아래의 버튼을 누르시면 “새가족 등록” 과정이 자세히 설명되어 있는 페이지로 이동합니다.
KCPC는 한 사람 한 사람을 그리스도의 제자로 세우려 노력하고 있습니다.
-
한어권 회중 (Korean Congregation)
와싱톤중앙장로교회는 ‘성도를 살리고 훈련해 지역과 세상을 변화시키는 글로컬교회(Glocal Church)’라는 비전으로 예수님의 목회 정신을 따라 말씀, 기도, 전도의 정신으로 그리스도의 제자를 세우려 노력하고 있습니다.
-
영어권 회중 (English Congregation)
우리는 예수 그리스도를 주님, 구원자, 왕으로 고백하고 따르는 사람들의 공동체입니다. 우리는 신령과 진정으로 하나님을 예배하고, 복음으로 변화되고 전하며, 함께 믿음을 실천하는 사랑의 공동체입니다.
-
DC 캠퍼스 (KCPC DC Campus)
KCPC DC는 복음 전도와 지역사회 봉사의 유산을 가진 교회로서 D.C. 수도권에 위치합니다. 하나님은 예수 그리스도를 통해서 우리를 참된 삶과 새로운 사명으로 회복하실 것입니다. 우리 모두는 예수님을 바로 알기 원합니다.
예배 안내
주일예배
1부 8:00 am | 2부 10:00 am | 3부 12:15 pm | 4부 2:30 pm
새벽기도회
월~금 6:00 am
토요새벽기도회
토 6:30 am
```

```json
{
  "denomination": "Presbyterian",
  "service_languages": [
    "Korean",
    "English"
  ]
}
```

---
