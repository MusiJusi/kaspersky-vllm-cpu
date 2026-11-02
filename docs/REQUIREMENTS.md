# Соответствие требованиям

[README](../README.md) · [Архитектура](ARCHITECTURE.md) · [Результаты проверок](VALIDATION.md)

Реализация тестового задания Data Engineer для команды исследования технологий машинного обучения.

## Основная часть

| Требование | Реализация |
| --- | --- |
| Kubernetes или Minikube | Minikube; namespace, Deployment, Service и PVC в [k8s/base](../k8s/base) |
| Открытая instruct-модель | SmolLM2-135M-Instruct; ID и commit SHA в [model.env](../k8s/base/config/model.env) |
| Строго CPU, vLLM ≥ 0.27.0 | vLLM `0.27.1+cpu`, PyTorch `2.13.0+cpu`; runtime-проверка backend и отсутствия CUDA |
| Собственный Dockerfile, запуск без root | [Dockerfile](../Dockerfile), UID/GID `10001:10001`, securityContext в Deployment |
| Полный pinned requirements.txt | [Сервер](../requirements.txt) и [загрузчик](../downloader/requirements.txt): прямые и транзитивные зависимости с SHA256 |
| Кастомное логирование | [SafeJsonFormatter](../src/app/safe_logging.py), [audit middleware](../src/app/audit.py), [logging.json](../config/logging.json) |
| Приватность stdout/stderr | Промпты, ответы и ключи не выводятся; факт обращения сохраняется с безопасными метаданными |
| Автоматическая первая загрузка на PVC | [download_model.py](../src/app/download_model.py), общий volume и проверка целостности snapshot |
| Повторный запуск без сети за моделью | Готовая копия проверяется локально; сервер использует offline-режим |
| HF-токен и API-токен через Secret | `vllm-secrets`: `hf-token` только загрузчику, `api-token` серверу |
| Параметры через ConfigMap | [kustomization.yaml](../k8s/base/kustomization.yaml); обновление без пересборки образа |
| Локальный запуск и исходный код | [README](../README.md), [эксплуатация](RUNBOOK.md), Dockerfile, манифесты, загрузчик и код логирования |

## Дополнительная часть

| Бонус | Реализация |
| --- | --- |
| Kustomize | Общая база и overlays `local` / `ci`; запуск через `kubectl apply -k` |
| Отдельный rootless initContainer | [downloader/Dockerfile](../downloader/Dockerfile), без PyTorch и vLLM |
| Нагрузочный тест и анализ | 300 измерений, короткий/длинный ввод, TTFT, latency, throughput; [результаты и выводы](BENCHMARK.md) |

Проверки и фактические ограничения описаны в [VALIDATION.md](VALIDATION.md).
