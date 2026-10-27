# Автоматический синтетический прогон
Manifest: `a2d530f0603a2788df8e1c49141e1ab906c3f1fb964ece295ad0d12e462b60b5`. Формальные проверки и известные регрессии; не клиническая валидация.

| Модель / маршрут / инструкция | Этап | n | Корректные | Быстрые корректные | p50 / p95 (с) | Ошибки |
| --- | --- | ---: | ---: | ---: | --- | --- |
| meta-llama/llama-3.1-8b-instruct / groq / russian | screen | 4 | 4 | 4 | 1.192 / 1.457 | {} |
| meta-llama/llama-3.1-8b-instruct / groq / russian | qualify | 24 | 14 | 14 | 1.373 / 2.457 | {"wrong_status": 8, "wrong_categories": 6, "invalid_json_schema_evidence": 2} |

Результат выбора: null
