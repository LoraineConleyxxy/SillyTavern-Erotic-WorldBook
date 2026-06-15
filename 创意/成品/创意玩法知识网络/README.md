# 创意玩法知识网络

本目录只保留当前可用的成品主文件和必要维护说明。

## 当前主文件

- `极品调教大世界书_十二卷版.json`：Worldbook 底库，后续新增和分类调整都以此文件为准。
- `极品调教快捷回复_十二卷无状态版.json`：由核心脚本生成的 Quick Reply 导入文件。

## 归档

- `归档/20260606_历史备份/`：整理前已经存在的 `.bak` 历史文件。
- `归档/20260606_分类调整前/`：本次卷十一分类补强前的主文件快照。

## 构建方式

如需刷新 Quick Reply，运行：

```bash
python3 /Users/mac/SIllyTavern_test/创意/核心脚本/build_global_qr.py
```

如果当前终端的 `python3` 找不到 `jieba`，使用本机已验证可用的解释器：

```bash
/opt/miniconda3/bin/python3 /Users/mac/SIllyTavern_test/创意/核心脚本/build_global_qr.py
```

不要手工改生成后的 Quick Reply；分类规则和条目归属优先改 Worldbook 的 `comment` 前缀或核心脚本规则。
