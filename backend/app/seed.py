from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import (
    Comment,
    Issue,
    Like,
    Post,
    Product,
    Recall,
    Report,
    ReportIssue,
    TimelineEvent,
)
from .pipeline.cluster import attach_and_dedupe

NOW = datetime(2026, 9, 25, 18, 0, 0)

CITIES = {
    "Atlanta": (33.75, -84.39),
    "Marietta": (33.95, -84.55),
    "Decatur": (33.77, -84.30),
    "Boston": (42.36, -71.06),
    "Chicago": (41.88, -87.63),
    "Austin": (30.27, -97.74),
    "Seattle": (47.61, -122.33),
}

ISSUES = [
    ("overheating", "Overheating", "Device becomes unusually hot during normal use.", "thermal", "🔥"),
    ("burning-odor", "Burning odor", "Reports of burning plastic or electrical odor.", "thermal", "🔥"),
    ("smoke", "Smoke", "Visible smoke during use.", "fire", "💨"),
    ("unexpected-shutdown", "Unexpected shutdown", "Device powers off without input.", "electrical", "⚡"),
    ("battery-swelling", "Battery swelling", "Battery pack appears swollen or deformed.", "battery", "🔋"),
    ("skin-irritation", "Skin irritation", "Users describe redness or itching after contact.", "dermal", "🟡"),
    ("choking-hazard", "Choking hazard", "Small parts detached.", "physical", "⚠️"),
    ("shock", "Electrical shock", "Users describe a shock or spark.", "electrical", "⚡"),
    ("leak", "Leak", "Unexpected leaking of liquid or contents.", "containment", "💧"),
    ("fire", "Fire", "Open flame reported during use.", "fire", "🔴"),
]


def seed_if_empty(db: Session) -> None:
    if db.query(Product).count():
        return
    seed(db)


def seed(db: Session) -> None:
    issues = {}
    for slug, name, description, category, icon in ISSUES:
        row = Issue(slug=slug, name=name, description=description, category=category, icon=icon)
        db.add(row)
        db.flush()
        issues[slug] = row

    products = _products()
    for product in products:
        db.add(product)
    db.flush()
    by_slug = {p.slug: p for p in products}

    _add_recalls(db, by_slug)
    _add_acme_reports(db, by_slug["acme-x100"], issues)
    _add_harborline(db, by_slug["harborline-cooker-6"], issues)
    _add_nimbus(db, by_slug["nimbus-sleep-headphones"], issues)
    _add_brookfield(db, by_slug["brook-field-m2"], issues)
    _add_pinecrest(db, by_slug["pinecrest-heater"], issues)
    _add_aerosip(db, by_slug["aerosip-bottle"], issues)
    _add_solara(db, by_slug["solara-blender"], issues)
    _add_lumenix(db, by_slug["lumenix-lamp"], issues)
    _add_valeo_kindred_posts(db, by_slug, issues)
    db.commit()

    for report in db.query(Report).all():
        attach_and_dedupe(db, report)
    db.commit()


def _products() -> list[Product]:
    return [
        Product(
            slug="acme-x100",
            brand="Acme",
            name="Acme X100 Air Purifier",
            model="X100",
            category="Home Appliances",
            upc="0840001111001",
            manufacturer="Acme Home Systems",
            summary="Compact bedroom air purifier. Primary demo product: no official recall, emerging community signal.",
        ),
        Product(
            slug="harborline-cooker-6",
            brand="Harborline",
            name="Harborline Instant Cooker 6qt",
            model="HIC-6",
            category="Kitchen",
            upc="0840002222002",
            manufacturer="Harborline Kitchen Co.",
            summary="Historical-style demo: community reports arrived before an official recall was issued.",
        ),
        Product(
            slug="nimbus-sleep-headphones",
            brand="Nimbus",
            name="Nimbus Sleep Headphones",
            model="NS-2",
            category="Personal Care",
            upc="0840003333003",
            manufacturer="Nimbus Audio",
            summary="Elevated community reports of skin irritation. No official recall identified.",
        ),
        Product(
            slug="valeo-night-light",
            brand="Valeo",
            name="Valeo Kids Night Light",
            model="VL-K9",
            category="Children's Products",
            upc="0840004444004",
            manufacturer="Valeo Lighting",
            summary="Official-style recall seed for a small-part hazard.",
        ),
        Product(
            slug="brook-field-m2",
            brand="Brook & Field",
            name="Brook & Field Baby Monitor M2",
            model="M2",
            category="Baby",
            upc="0840005555005",
            manufacturer="Brook & Field",
            summary="Emerging overheating reports clustered around Atlanta.",
        ),
        Product(
            slug="solara-blender",
            brand="Solara",
            name="Solara Portable Blender",
            model="SPB-1",
            category="Kitchen",
            upc="0840006666006",
            manufacturer="Solara Outdoors",
            summary="A few isolated reports. Used to show a quiet product.",
        ),
        Product(
            slug="pinecrest-heater",
            brand="Pinecrest",
            name="Pinecrest Ceramic Heater",
            model="PC-H200",
            category="Home Appliances",
            upc="0840007777007",
            manufacturer="Pinecrest Comfort",
            summary="Strong emerging signal with several geographic clusters.",
        ),
        Product(
            slug="lumenix-lamp",
            brand="Lumenix",
            name="Lumenix LED Desk Lamp",
            model="LX-D1",
            category="Home",
            upc="0840008888008",
            manufacturer="Lumenix",
            summary="Control product with no meaningful safety signal.",
        ),
        Product(
            slug="aerosip-bottle",
            brand="AeroSip",
            name="AeroSip Insulated Bottle",
            model="AS-32",
            category="Kitchen",
            upc="0840009999009",
            manufacturer="AeroSip",
            summary="Community discussion about lid leaks. Not a strong signal.",
        ),
        Product(
            slug="kindred-blanket",
            brand="Kindred",
            name="Kindred Electric Blanket",
            model="KEB-Q",
            category="Home",
            upc="0840001010101",
            manufacturer="Kindred Comfort",
            summary="Official-style overheating recall seed.",
        ),
    ]


def _add_recalls(db: Session, products: dict[str, Product]) -> None:
    db.add_all(
        [
            Recall(
                product_id=products["harborline-cooker-6"].id,
                agency="CPSC",
                recall_date=datetime(2026, 9, 12),
                reason="The sealing ring can dislodge under pressure, allowing hot contents to eject.",
                hazard="Burn hazard",
                source_url="https://demo-sources.signal.local/recalls/harborline-hic-6",
                official=True,
            ),
            Recall(
                product_id=products["valeo-night-light"].id,
                agency="CPSC",
                recall_date=datetime(2026, 8, 4),
                reason="Decorative cap can detach, creating a small part that may pose a choking hazard to young children.",
                hazard="Choking hazard",
                source_url="https://demo-sources.signal.local/recalls/valeo-vl-k9",
                official=True,
            ),
            Recall(
                product_id=products["kindred-blanket"].id,
                agency="CPSC",
                recall_date=datetime(2026, 7, 18),
                reason="The controller can overheat during extended use.",
                hazard="Fire hazard",
                source_url="https://demo-sources.signal.local/recalls/kindred-keb-q",
                official=True,
            ),
        ]
    )


def _report(
    db: Session,
    product: Product,
    issues: dict[str, Issue],
    *,
    source: str,
    text: str,
    days_ago: int,
    issue_slugs: list[str],
    city: str | None = None,
    title: str | None = None,
    url: str | None = None,
    source_id: str | None = None,
    user: bool = False,
    display_name: str | None = None,
    weight: float = 1.0,
) -> Report:
    lat = lng = None
    precision = "none"
    if city and city in CITIES:
        lat, lng = CITIES[city]
        precision = "city"
    created = NOW - timedelta(days=days_ago, hours=days_ago % 5)
    report = Report(
        product_id=product.id,
        source=source,
        source_id=source_id,
        source_url=url,
        title=title,
        text=text,
        excerpt=text[:220],
        created_at=created,
        incident_date=created - timedelta(hours=6),
        latitude=lat,
        longitude=lng,
        location_label=city,
        location_precision=precision,
        location_source="seed" if city else "none",
        is_user_generated=user,
        independence_weight=weight,
        display_name=display_name,
    )
    db.add(report)
    db.flush()
    for slug in issue_slugs:
        db.add(ReportIssue(report_id=report.id, issue_id=issues[slug].id, confidence=0.84))
    return report


def _add_acme_reports(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    templates = [
        ("community", 1, "Atlanta", ["overheating", "burning-odor"], "Started smelling like burning plastic after about 20 minutes on auto."),
        ("community", 1, "Atlanta", ["overheating"], "The top grille was too hot to touch. I unplugged it."),
        ("community", 2, "Marietta", ["burning-odor"], "Mine started overheating too. Same burning-plastic smell."),
        ("community", 2, "Decatur", ["unexpected-shutdown", "overheating"], "It shut itself off three times tonight and the housing was scorching."),
        ("web", 2, None, ["burning-odor"], "Public thread: X100 owners comparing a hot electrical odor after 15–30 minutes."),
        ("news", 3, None, ["overheating", "burning-odor"], "Local consumer blog collected similar X100 odor complaints this week."),
        ("community", 3, "Atlanta", ["smoke"], "A thin wisp of smoke from the back vent. No flame. Unplugged immediately."),
        ("community", 3, "Atlanta", ["overheating"], "Bedroom unit gets alarmingly hot on the lowest fan setting."),
        ("community", 4, "Boston", ["burning-odor"], "Bought last month. Tonight the room smelled like melted wiring."),
        ("community", 4, "Chicago", ["unexpected-shutdown"], "Random shutdowns plus a sharp smell. Not sure if related."),
        ("web", 4, None, ["overheating"], "Forum post describing the X100 housing warping near the motor."),
        ("community", 5, "Atlanta", ["burning-odor", "overheating"], "Same story as others: 20 minutes, then burning plastic."),
        ("community", 5, "Austin", ["overheating"], "Hotter than any purifier I have owned. I will not leave it overnight."),
        ("community", 6, "Seattle", ["burning-odor"], "Odor is strongest when the night mode starts."),
        ("community", 6, None, ["unexpected-shutdown"], "Keeps powering down. Manual says it should not thermal-trip this often."),
        ("news", 7, None, ["burning-odor"], "Neighborhood newsletter summarized several X100 odor reports. No recall listed."),
        ("community", 8, "Marietta", ["overheating"], "After 30 minutes the handle was painful to hold."),
        ("community", 9, "Decatur", ["burning-odor"], "I thought it was the candle. It was the purifier."),
        ("web", 10, None, ["overheating", "burning-odor"], "Archived discussion from last week: multiple owners, same heat-and-odor pattern."),
        ("community", 11, None, ["overheating"], "Noticed heat near the power brick more than the tower."),
        ("community", 12, "Atlanta", ["burning-odor"], "Guest room smelled like an electrical fire. Unit was the only thing on."),
        ("community", 13, "Boston", ["unexpected-shutdown"], "Shuts off, cools, then the smell comes back when I restart it."),
        ("community", 14, None, ["overheating"], "Older report: first heat complaint about two weeks ago."),
        ("community", 18, "Chicago", ["burning-odor"], "I assumed I bought a defective unit. Seeing others now."),
        ("community", 20, None, ["overheating"], "Baseline-period report: ran hot once, then seemed fine."),
        ("community", 22, "Austin", ["burning-odor"], "Faint odor on day one. Much stronger this month."),
        ("community", 24, None, ["unexpected-shutdown"], "One isolated shutdown last month. Logging it for the pattern."),
        ("web", 1, None, ["burning-odor", "overheating"], "Public comment: 'X100 smells like burning whenever I run it.'"),
        ("community", 1, "Atlanta", ["overheating"], "Third night in a row. I moved it away from the curtains."),
        ("community", 2, None, ["smoke"], "No fire. Smoke was brief. Still reporting it."),
        ("community", 3, "Marietta", ["burning-odor"], "Husband thought the outlet was melting. It was the X100."),
        ("community", 4, "Decatur", ["overheating"], "Auto mode seems worse than manual low."),
        ("community", 5, None, ["burning-odor"], "Reposting my own note so it sits with the other X100 reports."),
        ("community", 0, "Atlanta", ["overheating", "burning-odor"], "Tonight again. 20 minutes, burning plastic, I turned it off."),
        ("community", 0, None, ["unexpected-shutdown"], "Just happened: unexpected shutdown plus heat."),
        ("web", 0, None, ["overheating"], "Fresh public post matching the X100 heat cluster."),
        ("community", 1, "Boston", ["burning-odor"], "Same odor other people described. Adding my report."),
    ]
    names = ["jordan.k", "maya", "neighbor.atl", "lee", "samira", "chris.r", "priya", "devon"]
    for index, (source, days, city, slugs, text) in enumerate(templates):
        url = None
        if source in {"web", "news"}:
            url = f"https://demo-sources.signal.local/public/acme-x100/{index}"
        report = _report(
            db,
            product,
            issues,
            source=source,
            text=text,
            days_ago=days,
            issue_slugs=slugs,
            city=city,
            title="Acme X100" if source != "community" else None,
            url=url,
            source_id=f"acme-{index}",
            user=source == "community",
            display_name=names[index % len(names)] if source == "community" else None,
        )
        if source == "community" and index < 8:
            post = Post(
                product_id=product.id,
                report_id=report.id,
                display_name=report.display_name or "neighbor",
                title=text[:72],
                body=text,
                location_label=city,
                created_at=report.created_at,
            )
            db.add(post)
            db.flush()
            if index in {0, 1, 2}:
                db.add(Comment(post_id=post.id, display_name="kai", body="Same unit, same smell. I unplugged mine."))
                db.add(Like(post_id=post.id, display_name="kai"))
                db.add(Like(post_id=post.id, display_name="renee"))


def _add_harborline(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    texts = [
        (20, "Atlanta", "The ring would not seat. Steam shot sideways."),
        (19, "Chicago", "Hot contents hit the cabinet. I was standing to the side."),
        (18, None, "First public note about a loose Harborline ring."),
        (17, "Austin", "Ring popped during beans. No injury. Reporting anyway."),
        (16, "Atlanta", "Same ring slip as the other HIC-6 posts."),
        (16, "Boston", "Lid lifted a few millimeters under pressure."),
        (15, None, "Public thread collecting HIC-6 ring photos."),
        (15, "Marietta", "I replaced the ring. The new one slipped too."),
        (14, "Decatur", "Steam burst, then the cooker depressurized."),
        (14, "Chicago", "Two cooks in my building had the same thing this week."),
        (13, None, "Local blog: several HIC-6 ring complaints, no recall yet."),
        (13, "Atlanta", "I stopped using it after the third slip."),
        (12, "Seattle", "Ring walked out of the groove mid-cycle."),
        (12, "Austin", "Contents ejected. Burned the wooden spoon, not me."),
        (11, None, "More public posts using different words for the same ring failure."),
        (10, "Boston", "I thought I seated it wrong. Seeing a pattern now."),
        (9, "Atlanta", "Neighbor mentioned theirs did this last night."),
        (8, None, "Consumer newsletter summarized the cluster."),
        (7, "Chicago", "Still no official notice that I can find."),
        (6, "Austin", "Using a different cooker until this is clearer."),
        (5, None, "Archive of pre-recall HIC-6 reports."),
        (4, "Atlanta", "Adding mine for the timeline: ring slip, steam, no injury."),
    ]
    for i, (days, city, text) in enumerate(texts):
        source = "news" if "blog" in text or "newsletter" in text else ("web" if city is None else "community")
        _report(
            db,
            product,
            issues,
            source=source,
            text=text,
            days_ago=days,
            issue_slugs=["leak", "fire"] if "ejected" in text else ["leak"],
            city=city,
            url=f"https://demo-sources.signal.local/public/harborline/{i}" if source != "community" else None,
            user=source == "community",
            display_name="pre-recall" if source == "community" else None,
        )
    for day_offset, count, label in [
        (1, 3, "3 reports"),
        (2, 7, "7 reports"),
        (3, 14, "14 reports"),
        (4, 18, "Emerging signal detected"),
        (8, 22, "Official recall"),
    ]:
        db.add(
            TimelineEvent(
                product_id=product.id,
                day_offset=day_offset,
                label=label,
                event_type="recall" if "Official" in label else ("signal" if "Emerging" in label else "reports"),
                report_count=count,
                detail="Demonstration timeline built from seeded pre-recall reports. Not a claim that the live model predicted this recall.",
            )
        )


def _add_nimbus(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    notes = [
        (2, "Atlanta", "Redness where the ear pads sit after a full night."),
        (3, "Boston", "Itchy along the band. Stopped wearing them."),
        (4, None, "Public review: pads left a mark in the morning."),
        (5, "Chicago", "Irritation started week two."),
        (6, "Austin", "Same pad irritation other people mentioned."),
        (8, None, "Thread comparing pad materials."),
        (10, "Seattle", "Mild itching, posting because I see others."),
        (12, "Atlanta", "Went away when I stopped using them."),
        (1, "Decatur", "Woke up with a line of irritation. Describing, not diagnosing."),
    ]
    for i, (days, city, text) in enumerate(notes):
        source = "web" if city is None else "community"
        report = _report(
            db,
            product,
            issues,
            source=source,
            text=text,
            days_ago=days,
            issue_slugs=["skin-irritation"],
            city=city,
            url=f"https://demo-sources.signal.local/public/nimbus/{i}" if source == "web" else None,
            user=source == "community",
            display_name="sleep.user" if source == "community" else None,
        )
        if i < 3:
            db.add(
                Post(
                    product_id=product.id,
                    report_id=report.id,
                    display_name="sleep.user",
                    body=text,
                    location_label=city,
                    created_at=report.created_at,
                )
            )


def _add_brookfield(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    notes = [
        (1, "Atlanta", "Parent unit was hot enough that I took it off the nightstand."),
        (1, "Atlanta", "Camera brick smelled warm, almost electrical."),
        (2, "Marietta", "Same heat on the M2 adapter."),
        (2, "Decatur", "Adapter overheated overnight."),
        (3, "Atlanta", "Unplugged after the housing softened slightly."),
        (4, None, "Public post: M2 power brick running unusually hot."),
        (5, "Atlanta", "Two friends in town mentioned the same adapter heat."),
        (6, "Boston", "One out-of-area report with the same wording."),
        (0, "Atlanta", "Happened again tonight. Adding it."),
    ]
    for i, (days, city, text) in enumerate(notes):
        _report(
            db,
            product,
            issues,
            source="web" if city is None else "community",
            text=text,
            days_ago=days,
            issue_slugs=["overheating"],
            city=city,
            url=f"https://demo-sources.signal.local/public/m2/{i}" if city is None else None,
            user=city is not None,
            display_name="parent.atl" if city else None,
        )


def _add_pinecrest(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    cities = ["Atlanta", "Chicago", "Boston", "Austin", "Seattle", "Marietta", None, "Decatur"]
    for i in range(28):
        city = cities[i % len(cities)]
        text = [
            "Ceramic plate smelled like burning dust, then like wiring.",
            "Tip-over switch did not cut power when I nudged it.",
            "Front grille glowed brighter than last winter.",
            "Breaker tripped after 40 minutes.",
            "The handle side was much hotter than the label suggests.",
        ][i % 5]
        _report(
            db,
            product,
            issues,
            source="community" if city else "web",
            text=f"{text} Unit PC-H200.",
            days_ago=i % 9,
            issue_slugs=["overheating", "burning-odor"] if i % 2 == 0 else ["overheating"],
            city=city,
            url=f"https://demo-sources.signal.local/public/pinecrest/{i}" if not city else None,
            user=bool(city),
            display_name="winter" if city else None,
        )


def _add_aerosip(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    for i, text in enumerate(
        [
            "Lid gasket weeps if I lay the bottle on its side.",
            "Same slow leak other people mentioned. Annoying, not sure it is a safety issue.",
            "Coffee on the laptop sleeve. Posting the leak.",
        ]
    ):
        _report(
            db,
            product,
            issues,
            source="community",
            text=text,
            days_ago=4 + i,
            issue_slugs=["leak"],
            city="Atlanta" if i == 0 else None,
            user=True,
            display_name="commuter",
        )


def _add_solara(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    _report(
        db,
        product,
        issues,
        source="community",
        text="Blade coupling clicks more than I expected. No injury, logging it.",
        days_ago=16,
        issue_slugs=["unexpected-shutdown"],
        user=True,
        display_name="trail",
    )


def _add_lumenix(db: Session, product: Product, issues: dict[str, Issue]) -> None:
    # Intentionally empty: a quiet product should stay quiet.
    return


def _add_valeo_kindred_posts(db: Session, products: dict[str, Product], issues: dict[str, Issue]) -> None:
    _report(
        db,
        products["valeo-night-light"],
        issues,
        source="community",
        text="The star cap popped off in the crib. Official recall already covers this.",
        days_ago=9,
        issue_slugs=["choking-hazard"],
        city="Atlanta",
        user=True,
        display_name="caregiver",
    )
    _report(
        db,
        products["kindred-blanket"],
        issues,
        source="community",
        text="Controller was hot. I stopped using it when I saw the official notice.",
        days_ago=20,
        issue_slugs=["overheating"],
        city="Chicago",
        user=True,
        display_name="sleeper",
    )
    db.add(
        Post(
            product_id=products["valeo-night-light"].id,
            display_name="caregiver",
            title="Cap detached — following the official recall",
            body="Posting so other caregivers see the official notice in the community thread.",
            location_label="Atlanta",
            created_at=NOW - timedelta(days=9),
        )
    )
