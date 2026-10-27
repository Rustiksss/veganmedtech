# Результаты WORK-0020, редакции 8

Проверено 2026-10-27 (Europe/Moscow), генерации 2026-10-26 UTC. Аппрув: «WORK-0020, редакция 8 — одобряю». Задача не завершена и не архивирована: ни одна из 12 различных пар модель/маршрут не прошла четыре случая с каждым ответом <=10 с и медианой <=5 с. Существующий HTTPS остался на редакции 4; новых публикаций, смены POLZA_MODEL и удаления тегов WORK-0019 не было.

## Фактические результаты

- Журнал: 55/60 попыток всего, 54 генерирующих HTTP-запроса; 31 новая попытка редакции 8. Получено 11 пригодных ответов клиента/разбора, включая два минимальных приветствия; это не 11 пройденных сценариев и не сквозная приёмка. Часть других генераций завершалась у провайдера уже после нашего срока.
- Консервативная сумма верхних цен всех 31 новой попытки: 1,71049288 ₽ из разрешённых 3,60 ₽; остаток по верхним оценкам 1,88950712 ₽. Это не утверждение о фактическом списании. Для схемы дополнительно учтён её размер; для минимальных приветствий выход ограничен 64 токенами. Контроль приложения — максимум 512/18 с, каждый <=0,10 ₽. Автоповторов нет.
- Независимый curl: Groq/GPT-OSS-20B, минимальное приветствие — HTTP/1.1 4,672 с, HTTP/2 2,513 с, оба 200 и корректный ответ. Сам HTTP/1.1 не признан причиной всех задержек; зависимости/сеть сервера не менялись.
- Gemini 2.5 Flash Lite / Google AI Studio: компактная инструкция и обычный JSON mode возвращали лишний мусор после JSON; он отвергнут без очистки. Документированный строгий JSON Schema + temperature=0 дал положительный случай за 4,695 с (0,00694146 ₽), затем нейтральный запрос превысил 18 с. Явное reasoning.enabled=false дало корректный положительный ответ за 14,118 с — скорость не пройдена.
- Groq/GPT-OSS-20B с компактной схемой и обязательным low reasoning: корректный положительный ответ за 14,564 с. Ранее полный запрос получил 429; это не скрыто повтором в runtime.
- Solar Mini 4 / Upstage с компактной схемой, reasoning=none и sort=latency: 6,063 / 5,152 / 6,274 с для собственного упоминания/нейтрального/отрицания; прошлое — timeout 18 с. Кандидат не прошёл.
- Nex N2.5 Mini и Nova Micro с компактным контрактом: корректные положительные ответы за 16,837 / 12,709 с; остановлены по скорости.
- Qwen3.5-9B / Polza: положительный случай 2,527 с, нейтральный — 12,921 с и обычный текст вместо JSON. Заявленной поддержки JSON mode у маршрута нет, неподдерживаемое поле не отправлялось. Кандидат отвергнут.
- IBM Granite / Cloudflare и Qwen3.8 / Tenstorrent с компактным контрактом снова превысили 18 с. Полные результаты, ошибки, единичные успешные случаи и резервирование каждой попытки сохранены; они не заменены средним по избранным удачным ответам.

## Код, проверки и сервер

Неподтверждённые ветки Mistral/их allowlist и тесты предположений удалены. Рабочие client.py и prompts.py точно совпадают с опубликованной редакцией 4 (SHA-256 в server-state-rev8.json). Компактная инструкция/схема сохранена только как candidate-prompts-rev8.py для воспроизведения и дальнейшего согласованного исследования. Политика категорий и клинические правила не менялись.

Команды из корня:

- `python3 -m unittest discover -s tests -v`: 57 тестов, OK, 6,391 с, unit-rev8.txt.
- `python3 scripts/check_sdd.py`: OK, sdd-rev8.txt; повтор после обновления документации записывается отдельно.
- `docker compose --env-file /tmp/work0020-private/test.env -p veganmedtech-work0020-test -f compose.yaml -f /tmp/work0020-private/compose.test.yaml run --rm --no-deps -T --volume /home/rustiks/veganmedtech/backend/assistant:/app/backend/assistant:ro --volume /home/rustiks/veganmedtech/backend/config/settings.py:/app/backend/config/settings.py:ro app python manage.py test accounts care reports audit assistant -v 2`: 73 теста PostgreSQL, OK, 3,079 с, server-rev8.txt.
- Тот же изолированный run с `python manage.py makemigrations --check --dry-run`: No changes detected, migration-rev8.txt.
- Собственная тестовая БД остановлена, том сохранён, test-stop-rev8.txt.
- Чтение server-state-rev8.json: current/previous прежние, app/db/mailpit healthy, публичный HTTPS readiness=true со строгой проверкой TLS. Свободно 272658432 байта >=268435456. Ключи/данные/конфигурация сервера не копировались и не менялись. Новые браузерные проверки алерта/новый restore не выполнялись, так как предварительный выбор не пройден.

CHECK-02 failed; CHECK-08/09/10/11/12 blocked зависимостью от выбора. CHECK-01/04 сохраняют исторические свидетельства; CHECK-03/05/06/07 имеют прежние проверки и нынешние 73/57, но новый runtime/деплой не проверены и не объявляются пройденными. TD-001–TD-005 остаются resolved, нового технического долга не обнаружено. Клинического/правового допуска нет, только вымышленные данные.

## Свидетельства и первичные источники

[Журнал](polza-ledger.json), [верхний бюджет](r8-budget.json), [HTTP-контроль](protocol-control-rev8.jsonl), [Gemini JSON](screen-envelope-rev8.jsonl), [строгая схема](screen-schema-rev8.jsonl), [thinking off](screen-no-thinking-rev8.jsonl), [Groq схема](screen-groq-schema-rev8.jsonl), [Solar/Nex/Nova](screen-compact-routes-rev8.jsonl), [Cloudflare/Qwen](screen-final-routes-rev8.jsonl), [история собственных контролей](history-controls-rev8.json), [сервер](server-state-rev8.json), [серверные тесты](server-rev8.txt), [unit](unit-rev8.txt).

Синтаксис response_format/json_schema/strict и temperature проверен по [Polza Chat Completions](https://polza.ai/docs/api-reference/chat/completions); поддержка Gemini — по [Google structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en). Маршрут дополнительно проверен свежими метаданными Polza. Не заявляется, что схема гарантирует клиническую правильность или устраняет задержки.

Для возможного следующего плана прочитаны только бесплатные метаданные Llama 3.1 8B / Groq: 5,72686/9,162976 ₽ за миллион, JSON object поддержан, strict schema отклонён. [Groq](https://console.groq.com/docs/model/llama-3.1-8b-instant) описывает модель без reasoning для быстрых текстовых ответов, но её скорость через Polza ещё не проверена. GPT-4.1 nano исключён из кандидатов: каталог Polza его показывает, однако [официальная карточка OpenAI](https://developers.openai.com/api/docs/models/gpt-4.1-nano) помечает Shut down. Эти модели не вызывались. Новая генерация на 13-й паре выходит за согласованные 12.
