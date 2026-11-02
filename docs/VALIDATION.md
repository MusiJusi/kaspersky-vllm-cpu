# Проверки

[README](../README.md) · [Архитектура](ARCHITECTURE.md) · [Нагрузочный тест](BENCHMARK.md)

## Результаты

| Сценарий | Результат | Подтверждение |
| --- | --- | --- |
| CPU-инференс | vLLM `0.27.1+cpu`, CUDA отсутствует, UID `10001` | [Окружение](../results/environment.json) |
| API и Bearer auth | Генерация с токеном; `401` без него и с неверным токеном | [Интеграция](../results/integration.json) |
| Streaming и обработка ошибок | `[DONE]`, отказ при некорректном запросе, `404` для неизвестного маршрута | [smoke_test.py](../scripts/smoke_test.py) |
| Приватность логов | Контрольные промпты, ответы и токены не найдены в stdout/stderr; audit-запись присутствует | [Проверки до и после нагрузки](../results/extended/checks.json) |
| Offline-кэш и перезапуск | Готовая модель используется с PVC; повторная генерация успешна | [Интеграция](../results/integration.json) |
| ConfigMap без пересборки | `max_num_seqs`: 4 → 3 → 4; значение подтверждено, image ID прежний | [Конфигурация](../results/configuration.json) |
| Нагрузочная матрица | 300 измерений, 0 ошибок, по 32 выходных токена | [Измерения](../results/extended/benchmark.json) |
| Полный Linux CI | Unit-тесты, сборка, холодный старт, API, кэш и перезапуск | [GitHub Actions](https://github.com/MusiJusi/kaspersky-vllm-cpu/actions/runs/41511651299) |

Базовая локальная интеграция выполнена 31 октября 2026 года, расширенная нагрузка — 2 ноября.
Оборудование: Ryzen 9 9955HX, Linux engine Docker Desktop, Minikube 1.39.0, Kubernetes 1.37.0.
Версии, ресурсы, revision модели и image ID сохранены вместе с результатами.

## Unit-тесты

**17 тестов** проверяют авторизацию, приватность логов и streaming-аудит,
ограничения конфигурации, целостность snapshot, поведение загрузчика и нагрузочный скрипт.
Все пройдены в Linux-контейнере без сети и с read-only root filesystem.

Windows / PowerShell:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m unittest discover -s tests -v
```

На Windows два теста файловых блокировок пропускаются: они используют Linux `fcntl`.
Все тесты, из Linux shell с собранным образом загрузчика:

```bash
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount type=bind,source="$PWD/src",target=/app,readonly \
  --mount type=bind,source="$PWD/tests",target=/tests,readonly \
  --mount type=bind,source="$PWD/scripts",target=/scripts,readonly \
  --env PYTHONPATH=/app:/ \
  --entrypoint python kaspersky-model-downloader:dev \
  -m unittest discover -s /tests -v
```

## Интеграция

```shell
python scripts/check_cluster.py
```

Требуются работающий кластер `kaspersky-vllm-cpu`, свободный порт 8000
и файл `.local/api-token`. Скрипт сам открывает port-forward, проверяет API,
запускает временный Job проверки кэша и пересоздаёт Pod с сохранением PVC.
Готовая копия проверяется с заблокированными Python-сетевыми вызовами и импортом Hugging Face.

В CI используется `--benchmark`: дополнительно выполняется короткий прогон
из 8 запросов для каждого размера ввода с естественным завершением ответа.

## Нагрузочная матрица

Версия скрипта: `e05a3ec6e734bd572e431cad05678a13d382a602`.
На каждый из шести сценариев выполнены 3 прогрева и 50 измерений.
До и после нагрузки пройдены проверки API и приватности; ConfigMap, image ID,
Pod UID и число рестартов не изменились. Агрегаты сверены с отдельными измерениями.

[Методика](BENCHMARK.md) · [Данные](../results/extended/benchmark.json) ·
[Окружение](../results/extended/environment.json) · [Проверки](../results/extended/checks.json)

## CI и воспроизводимость

[Полный прогон](https://github.com/MusiJusi/kaspersky-vllm-cpu/actions/runs/41511651299)
проверил commit `e05a3ec6e734bd572e431cad05678a13d382a602` на чистом Linux:
17 unit-тестов, оба образа, пустой PVC, API, логи, нагрузку, offline-кэш и перезапуск.
[Статусы этапов](../results/extended/ci.json).

CI-профиль: 2 CPU, float32, контекст 2048, `max_num_seqs=2`.
Он отличается от локального BF16-профиля с лимитом 6 CPU; результаты между ними не объединяются.
Данные базового CI-прогона сохранены в [results/ci](../results/ci),
включая [ссылку на запуск и SHA256 архива](../results/ci/provenance.json).

## Область проверки

- Для локальной интеграции PVC заполнен ранее скачанным и проверенным snapshot.
  Автоматическая загрузка с пустого PVC отдельно проверена в CI.
- Используется общедоступная модель. Передача HF-токена через Secret настроена,
  но скачивание gated-модели с личным токеном не проверялось.
- Изменение ConfigMap проверено через `kubectl patch` и `rollout restart`;
  значение восстановлено. При обычном `apply -k` Kustomize меняет имя ConfigMap автоматически.
- Нагрузка из 300 измерений выполнена локально. Границы статистических выводов
  описаны в [методике](BENCHMARK.md#ограничения).
