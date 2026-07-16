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

> Examples named `DRAFT: ...` are awaiting human review — bootstrap uses
> this for pages where the production model disagrees with the reference
> labels. Review the disagreement, fix `expected` if the reference was
> wrong, then rename to `Example: ...`.

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

## DRAFT: Megachurch multi-site

- URL: _(fill in — e.g. a real Lifepoint / Elevation / North Point campus page)_
- Church ID: null

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

## DRAFT: AME historically Black

- URL: _(fill in — e.g. an AME church in Harlem or Atlanta)_
- Church ID: null

```text
St. Paul African Methodist Episcopal Church has served the Harlem community since 1887. Our Sunday morning worship at 10:45am is a Spirit-filled celebration of gospel music led by the Voices of St. Paul choir, with hammond organ, drums, and praise dancers. Communion is the first Sunday of each month. Reverend Dr. Carla Williams preaches the historic AME tradition of liberation and uplift — 'God Our Father, Christ Our Redeemer, the Holy Spirit Our Comforter, Humankind Our Family.' Ministries include the Sons of Allen men's group, Women's Missionary Society, Class Leaders Council, and a robust scholarship fund for Harlem youth pursuing HBCU education.
```

```json
{
  "denomination": "African Methodist Episcopal",
  "service_languages": ["English"],
  "programs_must_include_any": ["scholarship", "missionary", "men", "women"],
  "vibe_tags_must_include_any": ["gospel", "historically Black", "spirited", "traditional"],
  "worship_style": "gospel"
}
```

---

## DRAFT: Eastern Orthodox

- URL: _(fill in — e.g. holytrinitynyc.org or any GOARCH parish)_
- Church ID: null

```text
Holy Trinity Greek Orthodox Cathedral has been the spiritual home of the Greek Orthodox community for over a century. Divine Liturgy is celebrated every Sunday at 9:30am, primarily in Greek with English readings of the Epistle and Gospel. Vespers Saturday evening, Orthros precedes Sunday Liturgy. The choir chants Byzantine music a cappella in the traditional Greek style. Holy Communion is offered only to baptized Orthodox Christians in good standing who have prepared through prayer, fasting, and recent confession. Greek school for children meets Tuesday and Thursday evenings; the Philoptochos Society serves the poor; the GOYA youth group is active. We confess the faith of the Seven Ecumenical Councils, the unbroken Tradition of the undivided Church.
```

```json
{
  "denomination": "Greek Orthodox",
  "theological_stance": "traditional",
  "service_languages": ["Greek", "English"],
  "programs_must_include_any": ["Greek school", "Philoptochos", "GOYA"],
  "vibe_tags_must_include_any": ["liturgical", "Orthodox", "traditional"],
  "worship_style": "liturgical"
}
```

---

## DRAFT: Korean immigrant bilingual

- URL: _(fill in — e.g. a KAPC church in NoVA or Queens)_
- Church ID: null

```text
은혜한인교회 / Grace Korean Church is a multigenerational Korean-American congregation in Northern Virginia. We hold two Sunday services: the 9:00am Korean-language service for first-generation members with hymnal worship and traditional preaching, and the 11:30am English Ministry (EM) service for the 1.5 and second generation with contemporary praise band worship. We are part of the Korean American Presbyterian Church (KAPC) denomination, holding to the Westminster Confession. Our EM is led by Pastor David Kim. Programs include Korean language school for children on Saturdays, college fellowship (KCF), young adult ministry (YA), and dawn prayer (새벽기도) Tuesday through Saturday at 5:30am.
```

```json
{
  "denomination": "Korean American Presbyterian",
  "theological_stance": "traditional",
  "service_languages": ["Korean", "English"],
  "programs_must_include_any": ["Korean language school", "college", "young adult", "dawn prayer"],
  "vibe_tags_must_include_any": ["bilingual", "Korean", "intergenerational", "immigrant"]
}
```

---

## DRAFT: Quaker meeting

- URL: _(fill in — e.g. fmcquaker.org)_
- Church ID: null

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
  "worship_style": "silent"
}
```

---

## DRAFT: Sparse low-info page

- URL: _(fill in — a real bare-bones church website)_
- Church ID: null

```text
Riverside Community Church. Sunday services: 9am and 11am. 1247 Riverside Drive, Springfield, IL 62701. (217) 555-0184. office@riverside.org. Pastor Tom Reynolds. Established 1962.
```

```json
{}
```

---

## DRAFT: Saint Francis of Assisi Church (auto)

- URL: https://www.sfa-stb.org/
- Church ID: 111183
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: ["English", "Spanish", "Kreyol"] / reference: ["English", "Spanish", "Haitian Kreyol"])

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
    "Haitian Kreyol"
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

## DRAFT: The Gospel Tabernacle Church (auto)

- URL: https://gtcfranklinave.com
- Church ID: 113184
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: denomination (production: "Non-denominational" / reference: "Pentecostal"); service_languages (production: [] / reference: ["English"]); worship_style (production: null / reference: "charismatic")

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
  ],
  "worship_style": "charismatic"
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

## DRAFT: First Church of Christ, Scientist (auto)

- URL: https://christiansciencebrooklyn.org
- Church ID: 113730
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: denomination (production: "Christian Science" / reference: "Church of Christ, Scientist"); service_languages (production: [] / reference: ["English"])

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
  "denomination": "Church of Christ, Scientist",
  "service_languages": [
    "English"
  ]
}
```

---

## DRAFT: Church of Gethsemane (auto)

- URL: https://churchofgethsemane.org
- Church ID: 113956
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: theological_stance (production: null / reference: "progressive"); service_languages (production: [] / reference: ["English"])

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

## DRAFT: The Bridge Church (auto)

- URL: https://bridgechurchnyc.com
- Church ID: 115233
- Labeled by: google/gemini-2.5-pro on 2026-07-16 (bootstrap)
- Disagreements vs google/gemini-2.5-flash: service_languages (production: [] / reference: ["English"])

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
