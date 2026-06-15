---
name: sillytavern-ds-worldbook
description: Use when extracting adult SillyTavern worldbook play candidates from local Chinese novel TXT files with DeepSeek, classifying them with a target project's twelve-volume SillyTavern framework, appending them to the master worldbook, and rebuilding the Quick Reply export.
---

# SillyTavern DeepSeek Worldbook Pipeline

Use this skill for a SillyTavern creative-play worldbook project with this layout:

```text
<project-root>/
├── 核心脚本/build_global_qr.py
├── 成品/创意玩法知识网络/
│   ├── 极品调教大世界书_十二卷版.json
│   ├── _极品调教大世界书_十二卷版.json
│   └── 极品调教快捷回复_十二卷无状态版.json
└── 资料源/
```

1. DeepSeek extracts raw reusable adult play candidates from a local Chinese TXT novel.
2. Local code classifies raw entries into the current twelve-volume framework.
3. Optional append writes entries into the master worldbook.
4. Optional rebuild refreshes Quick Reply and the `_`-prefixed debug worldbook.

## Script

Run the bundled script:

```bash
python3 ~/.codex/skills/sillytavern-ds-worldbook/scripts/ds_worldbook_pipeline.py \
  --source "/absolute/path/to/novel.txt" \
  --slug "作者_标题" \
  --project-root "/absolute/path/to/创意" \
  --concurrency 10 \
  --append \
  --rebuild
```

The script prompts for the DeepSeek API key with hidden input if `DEEPSEEK_API_KEY` is not set. Do not put API keys in shell commands, files, logs, or skill docs.

## Outputs

For slug `作者_标题`, the script writes:

- `<project-root>/资料源/作者_标题_raw.json`
- `<project-root>/资料源/作者_标题_classified.json`

When `--append` is used, it creates an archive under:

- `<project-root>/成品/创意玩法知识网络/归档/<date>_<slug>_入库前/`

When `--rebuild` is used, it validates and refreshes:

- `极品调教大世界书_十二卷版.json`
- `_极品调教大世界书_十二卷版.json`
- `极品调教快捷回复_十二卷无状态版.json`

## Operating Rules

- Default DeepSeek concurrency is 10. Do not exceed 15.
- Always pass `--project-root` or set `SILLYTAVERN_CREATIVE_ROOT`; the distributed script does not assume a local user path.
- Raw extraction must not include category or subcategory fields.
- Classification uses `核心脚本/build_global_qr.py`; do not duplicate the category dictionaries in ad hoc code.
- Append entries with `classified_comment` as `comment`, clean title as `key[0]`, and `{标题}` at the start of content. Current `comment` format is `两位卷号+子分类_标题`, for example `01身份尊严粉碎_标题`.
- Use abstract identity words; do not preserve original character names.
- Filter or revise ordinary plot, plain sex-only water, and age-risk terms before final append when quality matters. If the user explicitly says “全塞”, append all classified entries after JSON/name-risk validation.
- After every append, rebuild QR and verify JSON parse for all three output files.
