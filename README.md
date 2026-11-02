# CPU inference with vLLM on Kubernetes

Тестовое задание Data Engineer (стажёр), команда исследования технологий
машинного обучения Kaspersky. Модель развёрнута в Minikube и отвечает через
OpenAI-compatible API строго на CPU.

**Проверено локально:** 17 тестов, Bearer-аутентификация, streaming,
приватность логов, offline-кэш на PVC, перезапуск Pod и изменение ConfigMap
без пересборки образа. Реальные замеры приведены ниже.

[Полный прогон CI на чистом Linux](https://github.com/MusiJusi/kaspersky-vllm-cpu/actions/runs/41511651299)
также завершился успешно.

[Архитектура](docs/ARCHITECTURE.md) · [Отчёт о проверках](docs/VALIDATION.md) ·
[Методика нагрузочных тестов](docs/BENCHMARK.md) · [Критерии задания](docs/REQUIREMENTS.md)

## Конфигурация

| Параметр | Значение |
| --- | --- |
| Модель | `HuggingFaceTB/SmolLM2-135M-Instruct` |
| Revision | `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| vLLM / PyTorch | `0.27.1+cpu` / `2.13.0+cpu` |
| Python в образах | `3.12.12`; базовый образ закреплён по digest |
| Локальный профиль | BF16, контекст 2048, `max_num_seqs=4`, KV cache 1 GiB |
| Minikube | 6 CPU, 10240 MiB RAM |
| Сервер | requests: 2 CPU / 4 GiB; limits: 6 CPU / 8 GiB |
| UID / GID | `10001:10001` в обоих образах |

Компактная открытая instruct-модель выбрана для уменьшения объёма загрузки
и стоимости CPU-проверки. На локальной машине подтверждены AVX512 и BF16.
Для CPU с AVX2 предусмотрен [CI-профиль с float32](k8s/overlays/ci).

## Локальный запуск на Windows

Нужны Docker Desktop с Linux engine, `kubectl`, Minikube и Python для клиентских
скриптов. Проверены Minikube `1.39.0` и Kubernetes `1.37.0`.
[Установка Minikube](https://minikube.sigs.k8s.io/docs/start/).
Также поддерживается локальный `.local/bin/minikube.exe`.

В PowerShell из корня репозитория:

```powershell
docker desktop start
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Скрипт собирает образы, создаёт отдельный кластер `kaspersky-vllm-cpu`,
загружает образы, создаёт Secret и применяет Kustomize. При первом запуске
initContainer автоматически скачивает модель на PVC. Для сборки и первой
загрузки нужен интернет. Дальнейшие запуски используют готовый snapshot.

Если образы уже собраны:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -SkipBuild
```

Работающий кластер используется повторно, существующий Deployment перезапускается
для применения актуальных локальных образов. PVC сохраняется.
`-ExecutionPolicy Bypass` действует только для запускаемого процесса PowerShell.

Случайный API-токен сохраняется в `.local/api-token` и передаётся через Secret.
Его значение не выводится в консоль и не передаётся аргументом команды.
Для выбранной открытой модели HF-токен не нужен. Для gated-модели перед запуском
задайте `HF_TOKEN` в окружении: он попадёт в Secret и только в initContainer.

В отдельном терминале откройте API на localhost:

```shell
kubectl --context kaspersky-vllm-cpu -n llm-inference port-forward service/vllm 8000:8000
```

Отправьте запрос из PowerShell:

```powershell
$apiToken = (Get-Content -LiteralPath .local\api-token -Raw).Trim()
$payload = @{
    model = 'local-instruct'
    messages = @(@{ role = 'user'; content = 'Explain containers in one sentence.' })
    max_tokens = 32
    temperature = 0
} | ConvertTo-Json -Depth 5
$result = Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/chat/completions `
    -Method Post -ContentType application/json `
    -Headers @{ Authorization = 'Bearer ' + $apiToken } -Body $payload
$result.choices[0].message.content
```

## Проверки

Закройте предыдущий port-forward: автоматическая проверка сама занимает порт 8000.

```shell
python scripts/check_cluster.py --benchmark
```

Проверяются ответы модели, 401 без токена и с неверным токеном, streaming,
ошибочный запрос, приватность логов, offline-кэш реального PVC и повторный
запуск после пересоздания Pod. Для проверки кэша Job запрещает Python-сетевые
вызовы и импорт HF. Результаты записываются в `results/` без промптов и ответов.

Отдельные команды:

```shell
python scripts/smoke_test.py
python scripts/benchmark.py --requests 8 --concurrency 2 --max-tokens 32
kubectl kustomize k8s/overlays/local
```

Первые две команды требуют открытого port-forward. Unit-тесты на Windows:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m unittest discover -s tests -v
```

Два теста file locking требуют Linux; команда для всех 14 тестов без сети
приведена в [отчёте](docs/VALIDATION.md). CI проверяет сборку и полный сценарий
в отдельном Minikube на Linux, включая первый запуск с пустым PVC.

## Настройки без пересборки

- [model.env](k8s/base/config/model.env): model ID, полный commit SHA и путь PVC.
- [runtime.env](k8s/base/config/runtime.env): KV cache и OpenMP.
- [inference.json](k8s/base/config/inference.json): dtype, контекст и batching.

После изменения:

```shell
kubectl --context kaspersky-vllm-cpu apply -k k8s/overlays/local
kubectl --context kaspersky-vllm-cpu -n llm-inference rollout status deployment/vllm
```

Kustomize меняет хэш имени ConfigMap, вызывая перезапуск Pod с сохранением PVC.
Проверено изменение `max_num_seqs` с 4 на 3 и обратно при неизменном image ID.

## Нагрузочные измерения

Расширенный прогон 2 ноября 2026 года: Ryzen 9 9955HX, CPU limit 6,
memory limit 8 GiB, BF16, KV cache 1 GiB, `max_num_seqs=4`.
По 50 измерений и 3 отдельных прогревочных запроса на серию;
параллелизм клиента 1, 2 и 4. Всего **300 измерений, 0 ошибок**.

После открытия port-forward из раздела запуска:

```shell
python scripts/benchmark.py --requests 50 --concurrency-levels 1 2 4 --max-tokens 32 --warmup-requests 3 --ignore-eos --output results/extended/benchmark.json
```

Все ответы содержат ровно 32 выходных токена (`ignore_eos=true`), поэтому
объём генерации одинаков. Вход содержит 84 или 918 токенов, включая шаблон
чата и уникальные идентификаторы перед контекстом. Параметры сервера,
образ и Pod во время измерений не менялись.

| Ввод | Параллелизм | Входных токенов | TTFT p50, с | TTFT p95, с | Latency p50, с | Latency p95, с | Output токенов/с | Запросов/с |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Короткий | 1 | 84 | 0.106 | 0.175 | 1.693 | 1.872 | 19.05 | 0.60 |
| Длинный | 1 | 918 | 0.501 | 0.579 | 2.079 | 2.211 | 15.52 | 0.48 |
| Короткий | 2 | 84 | 0.195 | 0.218 | 1.694 | 1.795 | 38.02 | 1.19 |
| Длинный | 2 | 918 | 0.707 | 0.993 | 2.583 | 2.689 | 24.93 | 0.78 |
| Короткий | 4 | 84 | 0.288 | 0.298 | 1.788 | 1.902 | 69.00 | 2.16 |
| Длинный | 4 | 918 | 1.305 | 1.807 | 3.546 | 3.903 | 35.47 | 1.11 |

Для короткого ввода переход 1 → 4 увеличил throughput в **3,62 раза**;
медиана полной задержки выросла примерно на 6%, но TTFT — с 0,106 до 0,288 с.
Для длинного ввода throughput вырос в **2,29 раза**, а медиана задержки —
на 71%, с 2,079 до 3,546 с. Из проверенных уровней 4 даёт наибольшую
пропускную способность; для длинных интерактивных запросов 1–2 может быть
предпочтительнее по задержке. Это вывод для данной конфигурации и одного прогона.

[Измерения](results/extended/benchmark.json) · [Окружение](results/extended/environment.json) ·
[Проверки API и приватности](results/extended/checks.json) · [Методика и ограничения](docs/BENCHMARK.md).
TTFT измеряется до первого непустого content delta, latency — до `[DONE]`;
throughput — за время всей серии без прогрева. p95 использует nearest rank:
при 50 запросах это 48-е значение по возрастанию. Начальный прогон с 8 запросами
сохранён в [results/benchmark.json](results/benchmark.json); длина выхода в нём
переменная, поэтому его показатели напрямую с этой таблицей не сравниваются.

### Настройка throughput

Для большого потока коротких запросов стоит проверить увеличение `max_num_seqs`
и `max_num_batched_tokens`, чтобы объединять больше запросов в batch.
Prefix caching полезен при повторяющихся префиксах. Параллелизм увеличивается
до насыщения CPU; дальнейший рост может ухудшить задержки.

Для меньшего числа запросов с длинным контекстом стоит проверить chunked prefill
и подобрать `max_num_batched_tokens`. `max_model_len` ограничивается фактической
потребностью. Для большого контекста может понадобиться больше
`VLLM_CPU_KVCACHE_SPACE` вместе с memory limit. OpenMP threads и binding
согласуются с выделенными CPU. В измерениях выше длинный ввод увеличил TTFT
при одинаковой длине выхода. Влияние изменения самих параметров сервера
требует отдельного эксперимента: в этой матрице менялся только параллелизм клиента.

## Сборка, безопасность и сдача

Оба образа собираются из собственных Dockerfile. Все Python-зависимости,
включая транзитивные, закреплены в `requirements.txt` с SHA256.
Основной контейнер работает offline, модель монтируется только для чтения.
Настройка логов, rootless-режим, работа секретов, ручной деплой в другой кластер
и обновление lock-файлов описаны в [ARCHITECTURE.md](docs/ARCHITECTURE.md).

Оригинал задания, реальные токены, веса и сырые логи исключены через `.gitignore`.
Для сдачи проверяющим нужно предоставить доступ к репозиторию и загрузить файл
со ссылкой, названный своей фамилией и инициалами с указанием команды.
