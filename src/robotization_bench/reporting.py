"""Display trusted evaluations and export a shift's event timeline."""

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from .contracts import Evaluation, RawReport


_REASONS = {
    "budget": "превышен бюджет покупки",
    "volume": "мало годных заказов хотя бы в один день",
    "on_time": "мало заказов в срок по сумме дней",
    "quality": "пропущено слишком много брака хотя бы в один день",
    "cost": "расходы не снизились",
    "labor": "активный труд не снизился",
    "automation": "доля автоматической упаковки ниже порога",
}


def _euros(cents: int) -> str:
    whole, fraction = divmod(abs(cents), 100)
    sign = "−" if cents < 0 else ""
    return f"{sign}{whole},{fraction:02} €"


def _cell(text: str) -> str:
    return " ".join(text.splitlines()).replace("|", r"\|")


def compare(evaluations: dict[str, Evaluation]) -> str:
    """Show each submitted evaluation on its own days, preserving caller order."""
    if not evaluations:
        return "Нет оценённых планов."

    rows = [
        "| План | Допустимость | Победа | Награда | Покупка | Расходы за все дни | "
        "Экономия к ручному | Труд / ручной, чел.·тики | Авто / все упаковки |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    outcomes = [
        "| План | Заказы | Годные | В срок | Пропущенный брак | Списано | Незавершено |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    notes = []
    for label, result in evaluations.items():
        name = _cell(label)
        reward = f"{result.reward_num}/{result.reward_den}"
        if result.valid:
            m = result.metrics
            values = [
                name, "да" if result.feasible else "нет", "да" if result.win else "нет",
                reward, _euros(m["purchase"]), _euros(m["total_cost"]),
                _euros(m["base_cost"] - m["total_cost"]),
                f"{m['labor_ticks']} / {m['base_labor_ticks']}",
                f"{m['auto_finished']} / {m['pack_finished']}",
            ]
            outcomes.append("| " + " | ".join([name, *(str(m[k]) for k in (
                "orders", "good", "on_time", "escaped", "scrap", "unfinished"
            ))]) + " |")
        else:
            values = [name, "невалидная сдача", "нет", reward, "—", "—", "—", "—", "—"]
        rows.append("| " + " | ".join(values) + " |")
        if result.reasons:
            details = ", ".join(_REASONS.get(r, _cell(r)) for r in result.reasons)
            notes.append(f"- {name} — {details}.")
    if len(outcomes) > 2:
        rows.extend(["", *outcomes])
    if notes:
        rows.extend(["", *notes])
    return "\n".join(rows)


def export_events(raw: RawReport, destination: Path) -> None:
    """Write one v1 Event per JSONL line, preserving order within each tick."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A reader opening the timeline during an export sees a complete file.
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                            dir=destination.parent, delete=False) as output:
        pending = Path(output.name)
        try:
            for event in raw.events:
                output.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")
            output.close()
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
