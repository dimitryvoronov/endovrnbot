"""Turn a list of diary rows into the numbers the dietitian report shows."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

OVEREAT_THRESHOLD = 3      # satiety_after >= 3  -> "с верхом" / "объелся"
ACCUM_HUNGER_THRESHOLD = 3  # hunger_before >= 3  -> "очень голоден" / "умираю"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def window(period_days: int):
    """Returns (since_iso, until_iso, now_dt, start_dt)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)
    return _iso(start), _iso(now), now, start


def aggregate(rows: list) -> dict:
    n = len(rows)
    if not n:
        return {"count": 0}

    hunger = [r["hunger_before"] for r in rows if r["hunger_before"] is not None]
    satiety = [r["satiety_after"] for r in rows if r["satiety_after"] is not None]
    overeat = [r for r in rows if (r["satiety_after"] or 0) >= OVEREAT_THRESHOLD]
    accum = [r for r in rows if (r["hunger_before"] or 0) >= ACCUM_HUNGER_THRESHOLD]

    triggers = Counter()
    for r in overeat:
        if r["company"]:
            triggers[f"С кем: {r['company']}"] += 1
        for d in json.loads(r["distractions"] or "[]"):
            triggers[f"С чем: {d}"] += 1
        if r["emotion"]:
            triggers[f"Эмоция: {r['emotion']}"] += 1

    return {
        "count": n,
        "avg_hunger": round(sum(hunger) / len(hunger), 1) if hunger else None,
        "avg_satiety": round(sum(satiety) / len(satiety), 1) if satiety else None,
        "overeat_episodes": len(overeat),
        "accum_hunger_episodes": len(accum),
        "top_triggers": triggers.most_common(5),
    }


def alerts(agg: dict, user) -> list[str]:
    """Simple heuristic flags. Extend with a real SCOFF screen later."""
    if not agg.get("count"):
        return ["Записей за период нет."]

    out = []
    if agg["avg_satiety"] is not None and agg["avg_satiety"] > 2:
        out.append("Среднее насыщение выше комфортного (ориентир 0–1) — возможно систематическое переедание.")
    if agg["overeat_episodes"] / agg["count"] >= 0.3:
        out.append(f"Переедание в {agg['overeat_episodes']} из {agg['count']} приёмов пищи за период.")
    if agg["accum_hunger_episodes"] and agg["overeat_episodes"]:
        out.append("Есть эпизоды накопленного голода и переедания — вероятны качели «ограничение → срыв».")
    # TODO: прогонять SCOFF-скрининг и выносить его результат сюда явным флагом.
    return out or ["Отклонений по текущим эвристикам не выявлено."]
