# Проверки решения

Локальная проверка выполнена 31 октября 2026 года на Ryzen 9 9955HX,
Linux engine Docker Desktop, Minikube 1.39.0, Kubernetes 1.37.0.
Версии, image ID, revision модели, настройки и ресурсы сохранены
в [environment.json](../results/environment.json).

## Подтверждённые результаты

| Проверка | Результат и свидетельство |
| --- | --- |
| CPU inference | Внутри работающего Pod: `backend=cpu`, `torch.version.cuda=None`, vLLM `0.27.1+cpu` |
| Rootless | UID `10001` в работающем сервере и отдельном образе загрузчика |
| Зависимости | Установка по полному lock с SHA256; `uv pip check` / `pip check` успешны |
| Сборка Kubernetes-конфигурации | Обе конфигурации Kustomize собираются |
| Аутентификация | Без токена и с неверным токеном — 401, с верным — успешная генерация |
| Streaming | SSE-ответ завершается `[DONE]` |
| Приватность | Контрольные промпты, ответы и токен отсутствуют в stdout/stderr сервера; запись обращения присутствует |
| Некорректный запрос | Отклонён с 400/422, контрольные строки не появляются в логах |
| Неизвестный путь и query | 404 с токеном; приватные части URL отсутствуют в логах |
| Скачивание модели | Rootless-загрузчик завершил первичную загрузку зафиксированной revision |
| Docker offline cache | Повторный запуск с `--network none` вернул `model_cache_hit` |
| Kubernetes offline cache | Отдельный Job на реальном PVC прошёл с запрещёнными Python-сетевыми вызовами и импортом HF |
| Перезапуск Pod | PVC сохранён, initContainer вернул `model_cache_hit`, API и проверка логов повторно успешны |
| ConfigMap без пересборки | `max_num_seqs`: 4 → 3 → 4; значение 3 подтверждено в `/proc/1/cmdline`, image ID не изменился |
| Нагрузка | По 8 streaming-запросов для короткого и длинного ввода; таблица в README |

Машиночитаемые результаты: [integration.json](../results/integration.json),
[configuration.json](../results/configuration.json),
[benchmark.json](../results/benchmark.json).

Изменение параметра проверялось через `kubectl patch ConfigMap` и
`rollout restart`; исходное значение восстановлено. В обычном сценарии
обновление через Kustomize меняет имя ConfigMap и инициирует rollout автоматически.

Для ускорения локальной проверки PVC был заполнен snapshot из уже проверенного
Docker volume. Холодный запуск на пустом PVC отдельно выполняется в CI.
Выбрана общедоступная модель: HF-токен пустой; передача через Secret настроена,
загрузка gated-модели с личным HF-токеном в этот прогон не входила.

## Unit-тесты

Все 14 тестов пройдены внутри Linux-контейнера с read-only root filesystem
и `--network none`. Проверяются:

- защита основных и вспомогательных API, правильный и неправильный токен;
- исключение сообщений, аргументов, traceback и warnings из приватных логов;
- аудит streaming без тела, заголовков, query string и клиентского request ID;
- запрет переопределения безопасности через параметры инференса;
- целостность snapshot, смена revision, незавершённая загрузка;
- отклонение путей за пределами snapshot и mutable revision;
- путь готового кэша при запрещённом импорте Hugging Face.

Команда для Linux shell:

```shell
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount type=bind,source="$PWD/src",target=/app,readonly \
  --mount type=bind,source="$PWD/tests",target=/tests,readonly \
  --entrypoint python kaspersky-model-downloader:dev \
  -m unittest discover -s /tests -v
```

На Windows используются команды из README; два Linux-теста file locking
пропускаются.

## Интеграционная проверка

```shell
python scripts/check_cluster.py --benchmark
```

Скрипт сам управляет port-forward и удаляет созданный для проверки кэша Job.
Порт 8000 должен быть свободен. API-токен читается из `.local/api-token`.
Проверка кэша требует отдельного небольшого CPU request, чтобы Job мог
разместиться вместе с сервером и control plane даже на двухъядерном CI-узле.

В CI используются два CPU, float32 и отдельный overlay. Автоматически
проверяются сборка обоих образов, холодный запуск в Minikube, API и приватность,
нагрузка, offline-кэш и перезапуск Pod.

[Успешный прогон](https://github.com/MusiJusi/kaspersky-vllm-cpu/actions/runs/41238914657)
проверил commit `ee1c86a74fb0a9d9df4cb87f0ac551224dd43fc1`.
Конфигурация: AMD EPYC 7763, limit 2 CPU, float32, контекст 2048,
`max_num_seqs=2`. Артефакт `cpu-validation-results` сохранён в репозитории:

- [результаты интеграции](../results/ci/integration.json);
- [измерения CI](../results/ci/benchmark.json);
- [окружение CI](../results/ci/environment.json);
- [ссылка на прогон и SHA256 архива](../results/ci/provenance.json).

Локальная таблица в README относится к отдельному BF16-профилю с limit 6 CPU;
условия каждого прогона зафиксированы отдельно.
