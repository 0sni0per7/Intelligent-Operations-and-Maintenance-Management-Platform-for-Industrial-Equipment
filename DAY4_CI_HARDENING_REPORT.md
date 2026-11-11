# Day 4 CI Hardening Report

日期：2026-11-11

## 修改范围

本次修改文件：

- `.github/workflows/test-backend.yml`
- `DAY4_CI_HARDENING_REPORT.md`

未修改：

- `compose.test.yml`
- `backend/.env.test.example`
- `backend/scripts/run_isolated_tests.py`
- `backend/pyproject.toml`
- 本地 `backend/.env.test`
- 生产 Compose、模型、API 和业务代码

## 关键差异

### 触发与超时

- 保留 `push`、`pull_request` 和 `workflow_dispatch`。
- `push` 仍只监听 `master`。
- `workflow_dispatch` 保持空配置，支持 GitHub Actions 页面手动运行。
- 未使用 `pull_request_target`。
- Job 超时从 5 分钟调整为 10 分钟。

### 一次性测试数据库密码

- 删除 GitHub Secret `TEST_POSTGRES_PASSWORD` 依赖，Fork PR 不再因无法读取 Secret 而失败。
- 使用 Python `secrets.token_hex(32)` 在 Runner 内生成一次性随机密码。
- 将以下两个值写入 Runner 内的 `backend/.env.test`：
  - `TEST_POSTGRES_PASSWORD`
  - `TEST_DATABASE_URL`
- 数据库 URL 与测试脚本校验规则一致：
  - 驱动：`postgresql+psycopg`
  - 主机：`127.0.0.1`
  - 端口：`5433`
  - 数据库：`app_test`
- `.env.test` 权限设置为 `0600`。
- 密码不打印、不写入 `$GITHUB_ENV`，`.env.test` 不在 Artifact 上传路径中。

### Compose 隔离

- 测试环境继续使用独立 Compose project。
- Project 名称现在包含 `github.run_id` 和 `github.run_attempt`，避免同一 Docker daemon 上的并行运行发生项目名冲突。
- `db-test` 启动和清理均使用同一份 `backend/.env.test`。
- 仅对 `compose.test.yml` 定义的独立测试项目执行 `down --volumes --remove-orphans`。
- 保留 Mailpit 启动和清理。
- 不针对开发数据库、开发数据卷或其他 Compose project 执行清理。

### 失败覆盖率报告

- `run_isolated_tests.py` 使用 `coverage run -m pytest tests/`，在 `backend/.coverage` 保存原始覆盖率数据。
- 使用临时数据文件验证：pytest 以非零状态退出后，coverage 数据文件仍会生成。
- 新增独立的 `Generate coverage HTML` 步骤，条件为 `if: always()`，从 `.coverage` 生成 `backend/htmlcov`。
- Artifact 上传步骤使用 `if: always()`，普通测试失败后仍会尝试上传。
- Artifact 上传设置 `if-no-files-found: error`，报告缺失时不会静默成功。
- `Run tests` 未设置 `continue-on-error`，原始测试失败状态不会被掩盖。

## 验证结果

- YAML 使用项目 `.venv` 中的 PyYAML 6.0.3 解析成功。
- 触发配置解析结果：`push`、`pull_request`、`workflow_dispatch`。
- Compose 密码变量确认为 `TEST_POSTGRES_PASSWORD`。
- 生成的环境文件变量与 Compose 配置一致。
- 数据库 URL 与 `run_isolated_tests.py` 的预期身份 `127.0.0.1:5433/app_test` 一致。
- HTML 输出目录确认为 `backend/htmlcov`。
- Coverage HTML 生成和 Artifact 上传均使用 `if: always()`。
- 清理步骤使用 `if: always()`，并复用同一个 `backend/.env.test`。
- Compose project 名称包含本次 Workflow 运行标识。
- `git diff --check` 退出码为 0；仅提示两个既有改动文件的 CRLF/LF 警告，无空白错误。

## 未解决风险

- 本次未启动 Docker，也未执行完整 GitHub Actions Job，因此镜像拉取、容器健康和实际 Runner 用时仍需在 GitHub 上验收。
- `actionlint` 未安装，GitHub Actions schema 校验采用了 YAML 解析和结构化断言。
- 如果测试在 coverage 开始记录前就失败，`.coverage` 可能不存在；此时 HTML 生成和 Artifact 上传会明确失败，但不会掩盖原始测试失败。
- GitHub Actions 对手动取消或 Job 硬超时的处理可能跳过 `if: always()` 步骤；10 分钟预算降低了普通超时风险，但不能完全消除该平台限制。
- Fork PR 的 Secret 隔离行为需在真实 Fork PR 上完成最终验收。

## GitHub 同步条件

文件层面已具备同步条件。同步后应在默认分支上手动运行一次 `Test Backend`，并验证 Fork PR 和测试失败 Artifact 场景。

本次未执行 Git commit、push、reset 或 clean。
