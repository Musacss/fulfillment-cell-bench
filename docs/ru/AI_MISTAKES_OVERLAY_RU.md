# HUD-оверлей ошибок ИИ и мультимодельная 3D-витрина (`AI_MISTAKES_OVERLAY_RU.md`)

> **Bilingual Guide (RU / EN):** Документ описывает подключение слоя диагностики ошибок ИИ (`diagnostics.json`) и мультимодельного сравнения (`frontier` vs `reference`, `frontier` vs `trained`) к 3D-сцене Мусы **без единого изменения священного формата `robotization-bench.replay.v1`**. English quick-reference is included below.

---

## 1. Быстрый запуск экспорта и CORS-сервера (RU)

1. **За одну команду экспортировать готовый 8-модельный 3D-пакет (`Manual`, `Reference`, `Claude Fable 5.2`, `Claude Opus 5.5`, `Gemini 3.1 Pro`, `Qwen 3.5-9B GRPO`, `Qwen 3.5-9B Base`, `Naive AI`):**
   ```sh
   PYTHONPATH=src python3 scripts/export_ai_mistakes_3d.py
   ```
   *(Если не передавать `--submission`, скрипт автоматически подхватывает все реальные прогоны из `docs/ru/examples/*.json` и пишет пакет в `artifacts/3d-ai-mistakes`.)*

   Либо передать свои JSON-планы явно:
   ```sh
   PYTHONPATH=src .venv/bin/python scripts/export_ai_mistakes_3d.py \
     --out artifacts/3d-ai-mistakes \
     --seeds 11 29 47 \
     --submission claude_opus55="Claude Opus 5.5 (Frontier)"=docs/ru/examples/claude_opus55_frontier.json \
     --submission qwen_grpo="Qwen 3.5-9B GRPO (Trained)"=docs/ru/examples/qwen35_grpo_win.json
   ```
   Экспортёр автоматически добавляет эталоны `manual` и `reference`, прогоняет 12 недель с `trace=True`, валидирует все сменные пакеты через `validate_quarter_pack(...)` и записывает `diagnostics.json` в каждую папку `quarterly-<slug>-seed<S>/`.

2. **Раздать пакет по HTTP с CORS для браузерного 3D-плеера:**
   ```sh
   .venv/bin/python scripts/serve_3d.py --dir artifacts/3d-ai-mistakes --host 127.0.0.1 --port 8765
   ```

## 2. Дерево файлов и URL (100% совместимость с `v1` плеером)

Каждая неделя `weeks/week-00` .. `weeks/week-11` остаётся **неизменённым** сменным пакетом `robotization-bench.replay.v1` (`manifest.json` + `events.jsonl`, `30s` на тик, те же 11 типов `Event`):

- `GET /index.json` — список всех прогонов `runs` (с полем `"diagnostics": "quarterly-<slug>-seed11/diagnostics.json"`) и готовых пар side-by-side `comparisons`:
  - `manual` vs `reference` (`baseline_vs_reference`)
  - `frontier` vs `reference` (`frontier_vs_reference`)
  - `frontier` vs `trained` (`frontier_vs_trained`)
- `GET /quarterly-<slug>-seed11/diagnostics.json` — каузальный разбор ошибок ИИ, карточки `hud_callout` и таймкоды сбоев `highlight_ticks`.
- `GET /quarterly-<slug>-seed11/quarter_manifest.json` — сводка 12 недель (`robotization-bench.quarter-pack.v1`).
- `GET /quarterly-<slug>-seed11/weeks/week-08/manifest.json` + `events.jsonl` — стандартный сменный реплей `v1` для существующего 3D-плеера.

## 3. Привязка `diagnostics.json` к элементам 3D HUD

### A. Верхний баннер результата (`overall`)
- `overall.win` / `overall.feasible` / `overall.valid` — бейдж статуса (`WIN` зелёный, `FEASIBLE (NO WIN)` жёлтый, `SLA FAILED` красный).
- `overall.reward_fraction` и `overall.reward_float` — точная награда (например, `32149023/90638275` / `0.354696`).
- `overall.total_cost_eur`, `overall.cost_delta_vs_manual_eur`, `overall.cost_delta_vs_reference_eur` — экономика квартала в евро (отрицательная дельта = экономия).
- `overall.headline_summary` — 1–2 готовые фразы с объяснением, **почему** план победил или провалился.

### B. Карточки главных ошибок ИИ (`key_mistakes[]`)
Отсортированы по критичности (`critical` -> `major` -> `minor`) и ущербу в центах (`euro_impact_cents`):
- `hud_callout` — короткая строка прямо для плашки поверх 3D-сцены, например:
  `Week 8 (Black Friday): Wear hit 12/12 with route='all' & no maintenance -> 55 jams, 92 late orders (-€1,840)`
- `category` — машинный код архетипа ошибки (`unstaffed_zone3_jam_deadlock`, `all_route_wear_blowout`, `bare_robot_commissioning_spike`, `skipped_pre_peak_maintenance`, `holiday_peak_understaffing`, `backlog_snowball`, `excess_idle_payroll`, `unprofitable_low_automation`).
- `week_range` (`[start_week, end_week]`) и `evidence_metrics` (`jams`, `wear_peak`, `carryover_peak`, `escaped`, `late`).

### C. Полоса 12 недель и кнопка «Прыжок к сбою» (`timeline_weeks[0..11]`)
Для каждой недели `w` (`0..11`):
- `status`: `"ok"` (зелёный) | `"warning"` (янтарный) | `"critical"` (красный) — подсветка ячейки недели в таймлайне.
- `active_mistakes`: массив строк-подсказок для выбранной недели.
- `highlight_ticks[]`: топ интервалов внутри `weeks/week-XX/events.jsonl`, куда можно мгновенно перемотать плеер:
  - `focus_tick`, `start_tick`, `end_tick` (логические тики `0..1080`)
  - `start_seconds`, `end_seconds` (`tick * 30` секунд анимации)
  - `kind`: `"jam_deadlock"` | `"jam"` | `"escaped"` | `"queue_bottleneck"` | `"scrap"`
  - `order_id`, `resource`, `stage`, `reason` — какую коробку `(runId, order_id)` или буфер `Q2/Q3/Q4` подсветить камерой!

---

## 4. English Quick Reference (HUD & Multi-Model Comparison)

### CLI Usage
```sh
PYTHONPATH=src .venv/bin/python scripts/export_ai_mistakes_3d.py \
  --out artifacts/3d-ai-mistakes \
  --seeds 11 29 \
  --submission frontier="Frontier LLM"=path/to/frontier.json \
  --submission trained="GRPO Trained Policy"=path/to/trained.json
```

### Key Guarantees
1. **Zero `v1` Replay Drift:** Every `quarterly-<slug>-seed<S>/weeks/week-00..11/` directory is a self-validated `robotization-bench.replay.v1` shift bundle (`manifest.json` + `events.jsonl`). Existing 3D shift playback requires zero parser changes.
2. **Side-by-Side Synchronization:** `index.json["comparisons"]` pairs `frontier` vs `reference` and `frontier` vs `trained` on the exact same `seed`. Scope 3D box entities by `(runId, order_id)`.
3. **Instant Failure Scrubbing:** `diagnostics.json["timeline_weeks"][w]["highlight_ticks"]` provides exact `[start_tick, end_tick]` and `focus_tick` intervals (`start_seconds = start_tick * 30`) grounded in `events.jsonl` so judges can jump directly to unassisted Zone-3 jam deadlocks, `route='all'` wear blowouts, escaped QC defects, or `Q2/Q3/Q4` buffer bottlenecks.
