# ArchaeoPairs

考古报告图文 Pair 数据构造多智能体管线。以《考古报告图文Pair数据构造_多智能体方案 V0.4》为唯一设计依据，采用 **LangGraph** 编排，实现"大图拆小图、图文配对、异常闭环"，产出（器物号, 图像, 描述文本）三元组语料。

## 架构

Supervisor-Worker 范式：S1–S10 十个智能体映射为 LangGraph StateGraph 节点，诊断驱动条件边回环（S6→S9→S6），checkpointer 断点续跑，interrupt 人工复核。

```mermaid
graph TD
  S1[S1 报告索引] --> S2[S2 器类判定器<br>5类决策路由]
  S2 -->|单器物线图/彩图| S7[S7 单器物解析器<br>整图=单一器物]
  S2 -->|多器物线图| MT[🔄 多器物线图处理管线 S3~S6]
  S2 -->|多器物彩图/其它| AR([归档/丢弃])
  subgraph MT ["多器物线图处理管线 (S3~S6)"]
    direction LR
    S3[S3 文本源解析器] --> S5[S5 融合仲裁器<br>双源三链对齐]
    S4[S4 图像源解析器<br>OCR序号/比例尺] --> S5
    S5 --> S6[S6 视觉分割器<br>SAM掩膜切分]
  end
  S7 --> S8[S8 单器物组装器<br>按artifact_id组装Pair]
  S6 --> S8
  S8 --> S9[S9 Supervisor VLM质检<br>诊断&回环≤3轮]
  S9 -->|合格| O[输出图文Pair]
  S9 -.->|缺陷:重切正文| S3
  S9 -.->|缺陷:重对齐| S4
  S9 -.->|缺陷:重分割| S6
  S9 -->|存疑/不合格| S10[S10 人工复核桥接器<br>Label Studio复核]
  S10 --> OUT[OUTPUT / PENDING_REVIEW]
```

## 环境要求

- Python >= 3.11
- 依赖见 `pyproject.toml`（锁定）与 `requirements.lock`

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# 或: .venv/bin/python -m pip install -e ".[dev]"  # Linux/macOS
.venv/Scripts/python -m pytest                    # 运行测试
```

跑批（P0，mock 能力接口），两种输入方式：

```bash
# 方式一：指定单本书（默认数据目录 books/，书名 = books/<书名>/data.xml）
.venv/Scripts/python -m archaeopairs.cli run-book --book 郑州商城
.venv/Scripts/python -m archaeopairs.cli run-book --book 郑州商城 --books-dir books/ --limit 30

# 方式二：指定目录批量跑所有书（books/<子目录>/data.xml）
.venv/Scripts/python -m archaeopairs.cli run-books
.venv/Scripts/python -m archaeopairs.cli run-books --books-dir books/
```

## 目录结构

```
src/archaeopairs/
  state.py               # pydantic v2 State/数据契约（§6.1）
  errors.py              # E-code 异常体系（§6.4）
  gateway.py             # 模型网关：录制/回放/重试（§9.1）
  capability/            # VLM/SAM/OCR 抽象 + mock 实现
  parsers/               # S1 XML / S3 图注(策略注册) / S3 正文
  agents/                # S1–S10 智能体模块
  orchestration/         # graph.py(StateGraph) / nodes.py / routing.py
  storage/               # SQLAlchemy 模型 + 对象存储
  schemas/               # JSON Schema 契约
  config/                # thresholds/flags 加载
tests/                   # 三层测试
ddl.sql                  # PostgreSQL DDL（§6.5）
migrations/             # Flyway/Liquibase 迁移脚本（V001__init.sql 起，§6.5.1）
config/*.example.yaml    # 配置样例（真实配置不入库）
```

## 配置

复制样例后编辑（真实配置不提交）：

```bash
cp config/thresholds.example.yaml config/thresholds.yaml
cp config/flags.example.yaml config/flags.yaml
```

## 数据与模型

- 书籍数据 `books/`（每本一个子目录，内含 `data.xml`；`books/*` 不入库）；media/原图与模型权重同样不入库，经对象存储/HuggingFace 获取。
- 能力接口（VLM/SAM/OCR）为抽象层，P0 用 `capability/mock.py`，生产可替换 transformers 实现。

## License

见 [LICENSE](LICENSE)（Apache-2.0）。
