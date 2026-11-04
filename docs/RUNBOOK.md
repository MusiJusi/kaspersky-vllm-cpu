# Эксплуатация

[README](../README.md) · [Архитектура](ARCHITECTURE.md) · [Проверки](VALIDATION.md)

## Окружение

Серверные образы рассчитаны на Linux amd64 и Python 3.12.
Для клиентских скриптов нужен Python 3.12+, для сборки требуется Docker с BuildKit.
Проверены Minikube 1.39.0 и Kubernetes 1.37.0.

| Профиль | Кластер | Лимит сервера | dtype / OpenMP |
| --- | --- | --- | --- |
| `local` | 6 CPU, 10240 MiB | 6 CPU, 8 GiB | BF16, 6 потоков |
| `ci` | 2 CPU, 5200 MiB | 2 CPU, 4 GiB | float32, 2 потока |

Профиль `local` проверен на Ryzen 9 9955HX с AVX512/BF16.
Профиль `ci` проверен на AMD EPYC 7763 и подходит для запуска без BF16.
Docker Engine должен располагать ресурсами для кластера и собственных служебных процессов.

## Windows / PowerShell

Основные команды приведены в [README](../README.md#запуск).
Скрипт поддерживает установленный Minikube из PATH и локальный `.local/bin/minikube.exe`.
`-ExecutionPolicy Bypass` применяется только к запускаемому процессу PowerShell.

Повторный запуск без сборки:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -SkipBuild
```

Работающий кластер используется повторно. При существующем Deployment скрипт
перезапускает Pod для загрузки актуальных локальных образов; PVC сохраняется.

## Linux / Bash

Команды выполняются из корня репозитория. Здесь используется профиль `ci` с float32.
Нужны `docker`, `minikube`, `kubectl` и `python3`; Docker должен быть запущен.

### 1. Образы и кластер

```bash
docker build -t kaspersky-model-downloader:dev -f downloader/Dockerfile .
docker build -t kaspersky-vllm-cpu:dev -f Dockerfile .
minikube start -p kaspersky-vllm-cpu --driver=docker \
    --cpus=2 --memory=5200 --kubernetes-version=v1.37.0 --keep-context
minikube image load -p kaspersky-vllm-cpu kaspersky-model-downloader:dev kaspersky-vllm-cpu:dev
kubectl --context kaspersky-vllm-cpu apply -f k8s/base/namespace.yaml
```

### 2. Секреты

API-ключ сохраняется в `.local/api-token` и используется повторно.
HF-токен берётся из переменной окружения `HF_TOKEN`; для открытой модели она может быть пустой.
Значения передаются в Kubernetes через stdin.

```bash
python3 - <<'PY'
import json
import os
import secrets
import subprocess
from pathlib import Path

token_file = Path('.local/api-token')
token_file.parent.mkdir(exist_ok=True)
if not token_file.exists():
    token_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
token = token_file.read_text(encoding='utf-8').strip()
if len(token) < 32:
    raise SystemExit('API token must contain at least 32 characters.')
secret = {
    'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
    'metadata': {'name': 'vllm-secrets', 'namespace': 'llm-inference'},
    'stringData': {'api-token': token, 'hf-token': os.environ.get('HF_TOKEN', '')},
}
subprocess.run(
    ['kubectl', '--context', 'kaspersky-vllm-cpu', 'apply', '-f', '-'],
    input=json.dumps(secret), text=True, check=True,
)
PY
```

### 3. Deployment

```bash
kubectl --context kaspersky-vllm-cpu apply -k k8s/overlays/ci
kubectl --context kaspersky-vllm-cpu -n llm-inference rollout status deployment/vllm --timeout=30m
python3 scripts/check_cluster.py
```

Последняя команда проверяет API, кэш и перезапуск, самостоятельно управляя port-forward.
Лимит первого запуска составляет 30 минут и включает скачивание модели.
`progressDeadlineSeconds` в Deployment и ожидание в скриптах согласованы с этим лимитом.
Для ручного обращения оставьте в отдельном терминале:

```bash
kubectl --context kaspersky-vllm-cpu -n llm-inference port-forward service/vllm 8000:8000
```

Для нового кластера с BF16 в шаге 1 используются `--cpus=6 --memory=10240`.
В шаге 3 применяется `k8s/overlays/local`.

## Токены и конфигурация

Secret `vllm-secrets` содержит два ключа:

| Ключ | Переменная контейнера | Получатель |
| --- | --- | --- |
| `api-token` | `VLLM_API_KEY` | Сервер |
| `hf-token` | `HF_TOKEN` | Только initContainer |

В Windows `HF_TOKEN` задаётся в окружении перед запуском `start-local.ps1`.
Модель и настройки находятся в [k8s/base/config](../k8s/base/config).
После изменения применяется нужный overlay через `kubectl apply -k`;
пересборка образа не требуется.

Для готовой модели загрузчик выдаёт событие `model_cache_hit`.
Основной сервер использует локальные файлы с `HF_HUB_OFFLINE=1` и `TRANSFORMERS_OFFLINE=1`.

## Диагностика

```shell
kubectl --context kaspersky-vllm-cpu -n llm-inference get pods,pvc
kubectl --context kaspersky-vllm-cpu -n llm-inference get events --sort-by=.lastTimestamp
kubectl --context kaspersky-vllm-cpu -n llm-inference logs deployment/vllm -c download-model
kubectl --context kaspersky-vllm-cpu -n llm-inference logs deployment/vllm -c server
```

| Ситуация | Что проверить |
| --- | --- |
| Docker Engine недоступен | Запущен ли Docker; выбран ли Linux engine |
| Pod остаётся `Pending` | Свободные CPU/RAM, события планировщика, наличие default StorageClass |
| Не найден локальный образ | Выполнен ли `minikube image load` для нужного профиля |
| API возвращает `401` | Токен из `.local/api-token` и заголовок `Authorization: Bearer …` |
| Проверка не занимает порт 8000 | Остановлен ли ручной port-forward |
| Ошибка при старте BF16 | Поддержка CPU; для запуска без BF16 используйте float32-профиль |

Тексты промптов, ответов и исключений в логи не выводятся. Доступны тип ошибки,
место её возникновения, статус и длительность запроса.

## Сборка и зависимости

Прямые зависимости указаны в `requirements.in` и `downloader/requirements.in`.
Полные `requirements.txt` фиксируют транзитивные зависимости и SHA256.
Для обновления используется `uv==0.13.6`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\lock.ps1
```

Для локального uv добавьте `-Uv .\.local\tools\bin\uv.exe`.
После обновления проверяются сборка и инференс.

С заполненным BuildKit-кэшем установка Python-зависимостей доступна offline:

```shell
docker build --build-arg UV_OFFLINE=1 -t kaspersky-vllm-cpu:dev .
```

Bootstrap uv и системные пакеты при отсутствии соответствующих слоёв требуют сеть.
Для другого Kubernetes-кластера образы загружаются в registry или на узлы;
имена образов и `imagePullPolicy: Never` меняются через Kustomize.
