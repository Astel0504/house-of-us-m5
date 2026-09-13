[简体中文](README.md) | [English](README_EN.md)

# House of Us — 冻结 M5 作品集快照

House of Us 是一个面向 AI 伴侣运行时的私有、本地优先连续性系统（continuity system）。它把连续性视为经过工程化设计的系统边界：provider 输出只是候选，由运行时策略负责评估；持久化状态变更则必须经过明确的契约、身份校验和仅追加式回执（append-only receipts）。

本仓库是冻结 M5 状态的公开作品集快照，包含经过清理、可公开审阅的 M5 连续性核心，以及精选的确定性本地测试，面向技术评审与本地检查。它不是私有 House 部署，也不包含生产数据、凭据、provider trace、Android 应用或私有仓库的 Git 历史。

## M5 展示的能力

- 与 provider 无关的请求/响应边界（provider-neutral boundary），将 provider transport 与 House 语义分离。
- 候选、评估与持久化写入（durable-write）分阶段处理，并明确划分各自的权限边界。
- 不可变操作身份、幂等性（idempotency）、前序绑定（predecessor binding）以及 fail-closed 恢复路径。
- 基于 SQLite 的本地连续性状态，包含事件、工作集（Working Set）、上下文与 outbox 结构。
- 确定性的上下文整形，以及紧凑的 provider-visible 投影。
- 基于最终 provider-facing material 生成的 prompt-cache identity，而不是依赖非正式的语义标签。
- 本地可观测性与脱敏契约，防止凭据和原始私密 body 进入普通诊断信息。
- 无 provider 的合成测试，用于验证契约、抵抗 replay、处理 scope、校验 cache identity 与 trace 安全性。

私有 M5 冻结记录将完整系统标记为 **M5 activated and verified**。本公开导出有意只呈现能够在 House 外部安全审阅的部分。

## 架构

```text
provider candidate
        |
        v
neutral request + runtime evaluation
        |
        v
identity / predecessor / scope / idempotency gates
        |
        v
local event store + Working Set + context projection
        |
        v
durable preparation outbox + receipts
        |
        v
provider-visible projection and diagnostics
```

关于所有权边界，请参阅 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；关于冻结快照的范围与解释，请参阅 [docs/M5_OVERVIEW.md](docs/M5_OVERVIEW.md)。

## 构建方式与协作分工

Astel 负责产品方向与验收标准，包括需求、架构决策、隐私边界、优先级、测试策略、失败分析以及最终验证。Codex 和其他 AI coding agents 在这一方向下，负责实现边界明确的模块、测试、文档和机械性工程重构。这体现的是产品与系统所有权，以及对 AI agent 工程协作的组织能力；并不声称 Astel 手工编写了并非由她亲自编写的代码。

## 本地检查

前置条件：Python 3.10 或更高版本。公开测试切片只使用 Python 标准库。

Windows PowerShell：

```powershell
$env:PYTHONPATH = "src;tests"
py -3.14 -m unittest discover -s tests -p "test_*.py"
```

macOS/Linux：

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_*.py'
```

这些测试是合成的本地测试，预期不会调用 provider、网络、部署或 canonical data。它们只覆盖公开导出的核心；测试通过并不等于证明私有服务、Android APK、subscription route 或 live provider configuration 已经可用。

## 范围与限制

本快照的边界是私有仓库记录的冻结 M5 commit。POST-M5 与 W1 开发不在其中。私有 gateway/UI、Android relay、live MCP/deployment bridge、运维 runbook、chat-history 与 Memory 导出、live traces、截图、生成物以及第三方源代码 checkout 均未包含，因为它们属于私有内容、依赖特定环境、承载数据，或对作品集审阅并非必要。具体省略项见 [docs/PUBLIC_SCOPE.md](docs/PUBLIC_SCOPE.md)。

本仓库不是可直接部署的完整系统，其中不包含 provider key、生产 endpoint、私有配置、数据库或真实对话数据。发布代码的目的仅是作品集展示与技术审阅。

## 许可证状态

本作品集快照不授予开源许可证。保留所有权利。私有仓库中列出的依赖未在此重新分发，复制的第三方 Drivesoid checkout 也已排除。一个 House 模块包含改编自 MIT 许可 MCP-client 组件的代码；其署名与声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
