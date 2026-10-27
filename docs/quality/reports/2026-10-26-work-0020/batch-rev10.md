# Автоматический синтетический прогон
Manifest: `19342fc655797fbd3b8e4a5f155fed62729960df28896ff9ae835ecf9b1f96f8`. Формальные проверки и известные регрессии; не клиническая валидация.

| Модель / маршрут / инструкция | Этап | n | Корректные | Быстрые корректные | p50 / p95 (с) | Ошибки |
| --- | --- | ---: | ---: | ---: | --- | --- |
| google/gemma-3-12b-it / deepinfra/bf16 / compact | screen | 4 | 2 | 2 | 6.3025 / 6.336 | {"timeout": 1, "wrong_categories": 1, "wrong_status": 1} |
| google/gemma-3-12b-it / deepinfra/bf16/priority / compact | screen | 4 | 3 | 3 | 3.056 / 4.464 | {"invalid_json_schema_evidence": 1} |
| google/gemma-3-27b-it / deepinfra/fp8 / compact | screen | 4 | 3 | 2 | 4.067 / 17.629 | {"timeout": 1} |
| qwen/qwen3.5-35b-a3b / darkbloom/fp4 / compact | screen | 4 | 3 | 3 | 2.281 / 3.215 | {"wrong_categories": 1, "wrong_status": 1} |
| meta-llama/llama-3.1-8b-instruct / groq / compact | screen | 4 | 4 | 4 | 1.6444999999999999 / 2.989 | {} |
| meta-llama/llama-3.1-8b-instruct / groq / compact | qualify | 24 | 18 | 17 | 1.421 / 10.392 | {"wrong_categories": 6, "wrong_status": 6} |
| meta-llama/llama-3.1-8b-instruct / novita/fp8 / compact | screen | 4 | 4 | 3 | 2.512 / 15.241 | {} |
| google/gemma-3-4b-it / parasail/bf16 / compact | screen | 4 | 3 | 3 | 4.363 / 6.603 | {"wrong_categories": 1, "wrong_status": 1} |
| mistralai/ministral-3b-2512 / mistral / compact | screen | 4 | 3 | 3 | 1.989 / 3.674 | {"wrong_categories": 1} |
| cohere/command-r7b-12-2024 / cohere / compact | screen | 4 | 2 | 2 | 5.3245000000000005 / 6.984 | {"timeout": 1, "wrong_categories": 1, "wrong_status": 1} |
| openai/gpt-oss-20b / groq / compact | screen | 4 | 4 | 4 | 3.125 / 5.321 | {} |
| openai/gpt-oss-20b / groq / compact | qualify | 24 | 19 | 17 | 2.584 / 14.546 | {"wrong_categories": 4, "wrong_status": 4, "http_503": 1} |
| google/gemma-3-12b-it / deepinfra/bf16 / russian | screen | 4 | 4 | 4 | 5.537000000000001 / 6.354 | {} |
| meta-llama/llama-3.1-8b-instruct / novita/fp8 / russian | screen | 4 | 3 | 3 | 2.214 / 4.127 | {"wrong_status": 1} |

Результат выбора: null
