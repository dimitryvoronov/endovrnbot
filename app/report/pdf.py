"""ReportLab PDF for the dietitian. Mirrors the structure of the reference bot's report:
profile / aggregates / alerts / raw entries / photos / disclaimer.
"""
import io
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from ..config import FONT_DIR, MEDIA_DIR

FONT = "Body"
FONT_B = "Body-Bold"
_registered = False

_MAC = Path("/System/Library/Fonts/Supplemental")
_FONT_CANDIDATES = [
    (FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (_MAC / "Arial Unicode.ttf", _MAC / "Arial Unicode.ttf"),
    (_MAC / "Arial.ttf", _MAC / "Arial Bold.ttf"),
]


def _register_fonts() -> None:
    global _registered
    if _registered:
        return
    for regular, bold in _FONT_CANDIDATES:
        if regular.exists():
            pdfmetrics.registerFont(TTFont(FONT, str(regular)))
            pdfmetrics.registerFont(TTFont(FONT_B, str(bold if bold.exists() else regular)))
            _registered = True
            return
    raise RuntimeError(
        "No Cyrillic TTF found. Run:  python scripts/fetch_fonts.py"
    )


def _style(name, size, leading, bold=False, grey=False):
    return ParagraphStyle(
        name, fontName=FONT_B if bold else FONT, fontSize=size, leading=leading,
        textColor=colors.grey if grey else colors.black,
    )


def _kv_table(pairs, body):
    data = [[Paragraph(str(k), body), Paragraph("" if v is None else str(v), body)]
            for k, v in pairs]
    t = Table(data, colWidths=[55 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E0E4EA")),
    ]))
    return t


def build_report(user, rows, agg, alerts_list, period_days, now, start) -> bytes:
    _register_fonts()
    body = _style("body", 9.5, 13)
    h1 = _style("h1", 15, 19, bold=True)
    h2 = _style("h2", 11, 15, bold=True)
    small = _style("small", 7.5, 10, grey=True)

    code = user["patient_code"] or "—"
    story = [
        Paragraph(f"Отчёт пациента {code}", h1),
        Paragraph(f"Период: с {start.strftime('%Y-%m-%d')} по {now.strftime('%Y-%m-%d')} "
                  f"(за {period_days} дн.)", body),
        Paragraph(f"Сгенерирован: {now.strftime('%Y-%m-%d %H:%M UTC')}", body),
        Spacer(1, 8),
    ]

    # 1. Профиль
    bmi = None
    if user["height_cm"] and user["weight_kg"]:
        bmi = round(user["weight_kg"] / (user["height_cm"] / 100) ** 2, 1)
    story += [
        Paragraph("1. Профиль пациента", h2),
        _kv_table([
            ("Псевдоним", user["pseudonym"] or "—"),
            ("Пол", user["sex"] or "—"),
            ("Возраст", user["age"] or "—"),
            ("Рост / вес / ИМТ",
             f"{user['height_cm'] or '—'} см · {user['weight_kg'] or '—'} кг · ИМТ {bmi or '—'}"),
            ("Активность", user["activity"] or "—"),
            ("Аллергии", user["allergies"] or "—"),
            ("Не любит", user["dislikes"] or "—"),
        ], body),
        Spacer(1, 4),
    ]

    # 2. Агрегаты
    story.append(Paragraph("2. Агрегаты по дневнику", h2))
    if agg.get("count"):
        story.append(_kv_table([
            ("Записей всего", agg["count"]),
            ("Средний голод ДО", f"{agg['avg_hunger']} (ориентир 2)"),
            ("Среднее насыщение ПОСЛЕ", f"{agg['avg_satiety']} (ориентир 0–1)"),
            ("Эпизодов переедания (≥3)", agg["overeat_episodes"]),
            ("Эпизодов накопл. голода (≥3 ДО)", agg["accum_hunger_episodes"]),
        ], body))
        if agg["top_triggers"]:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Контекст эпизодов переедания:", body))
            for label, cnt in agg["top_triggers"]:
                story.append(Paragraph(f"• {label} — {cnt}", body))
    else:
        story.append(Paragraph("Записей за период нет.", body))
    story.append(Spacer(1, 4))

    # 3. Алерты
    story.append(Paragraph("3. Алерты периода", h2))
    for a in alerts_list:
        story.append(Paragraph(f"• {a}", body))
    story.append(Spacer(1, 4))

    # 4. Все записи
    story.append(Paragraph("4. Все записи дневника", h2))
    if rows:
        data = [["Дата/время", "Приём", "Голод", "Насыщ.", "С кем", "С чем", "Эмоция"]]
        for r in reversed(rows):  # chronological in the table
            dz = ", ".join(json.loads(r["distractions"] or "[]")) or "—"
            data.append([
                r["ts"][5:16].replace("T", " "),
                r["meal_type"] or "—",
                "—" if r["hunger_before"] is None else r["hunger_before"],
                "—" if r["satiety_after"] is None else r["satiety_after"],
                r["company"] or "—",
                dz,
                r["emotion"] or "—",
            ])
        t = Table(data, repeatRows=1,
                  colWidths=[24 * mm, 22 * mm, 13 * mm, 14 * mm, 24 * mm, 34 * mm, 22 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C0CC")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F5")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_B),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("—", body))

    # 5. Фото
    photos = []
    for r in rows:
        for name in json.loads(r["photo_paths"] or "[]"):
            fp = MEDIA_DIR / name
            if fp.exists():
                photos.append((r["ts"][5:16].replace("T", " "), fp))
    if photos:
        story += [Spacer(1, 6), Paragraph("5. Фото приёмов пищи", h2)]
        grid, caps = [], []
        row_imgs, row_caps = [], []
        for ts, fp in photos:
            try:
                img = Image(str(fp), width=42 * mm, height=42 * mm, kind="proportional")
            except Exception:
                continue
            row_imgs.append(img)
            row_caps.append(Paragraph(ts, small))
            if len(row_imgs) == 3:
                grid.append(row_imgs); caps.append(row_caps)
                row_imgs, row_caps = [], []
        if row_imgs:
            row_imgs += [""] * (3 - len(row_imgs))
            row_caps += [""] * (3 - len(row_caps))
            grid.append(row_imgs); caps.append(row_caps)
        interleaved = []
        for imgs, cs in zip(grid, caps):
            interleaved.append(imgs)
            interleaved.append(cs)
        gt = Table(interleaved, colWidths=[55 * mm] * 3)
        gt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(gt)

    story += [
        Spacer(1, 12),
        Paragraph(
            "Документ создан автоматически. Образовательный материал для обсуждения с лечащим "
            "диетологом; не является медицинским изделием и не заменяет консультацию врача. "
            "Шкалы голода/насыщения — инструмент когнитивно-поведенческой работы с пищевым "
            "поведением.", small),
    ]

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"Дневник питания {code}",
    ).build(story)
    return buf.getvalue()
