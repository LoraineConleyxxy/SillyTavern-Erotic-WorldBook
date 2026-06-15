#!/usr/bin/env python3
import argparse
import copy
import getpass
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


DEFAULT_PROJECT_ROOT = os.environ.get("SILLYTAVERN_CREATIVE_ROOT")
AGE_RISK_RE = re.compile(r"幼态|未成年|小学生|中学生|萝莉|孩童|青春期少女")

NAME_REPLACEMENTS = {
    "丽塔·洛丝薇瑟": "女仆受虐者",
    "比安卡·阿塔吉娜": "旧恋人",
    "布洛妮娅": "受虐者",
    "洛丝薇瑟": "受虐者",
    "幽兰戴尔": "旧恋人",
    "雷电芽衣": "前战友",
    "亚当": "调教者",
    "比安卡": "旧恋人",
    "琪亚娜": "前战友",
    "德丽莎": "上司",
    "符华": "前辈",
    "希儿": "同伴",
    "姬子": "教师",
    "芽衣": "前战友",
    "卡萝尔": "后辈",
    "缇米朵": "后辈",
    "奥托": "支配者",
    "凯文": "支配者",
    "崩坏": "灾厄",
    "女武神": "战斗少女",
}

FRAMEWORK = """当前世界书十二卷框架供检索参考：
卷一：极致恶堕与崩坏；卷二：深度规训与服从；卷三：机械道具与拘束；卷四：百合与百合破坏；卷五：TSF性转与雌竞；卷六：催眠与常识篡改；卷七：异种孕育与魔物；卷八：高潮控制与排泄；卷九：公开暴露与社死；卷十：强制发情与体质改造；卷十一：服装与换装Play；卷十二：纯爱与温存。
本阶段只提取，不分类。不要输出卷名、category、subcategory。"""

SYSTEM_PROMPT = """你是成人向 SillyTavern 世界书的玩法候选提取器。你的任务是从小说片段中提取“可复用的玩法机制”，不是复述剧情。
硬性要求：
1. 只处理明确成年或成人语境角色；跳过未成年、年龄暧昧、幼态化内容。
2. 不保留原作角色名、人名、男主名、专有名；统一改成抽象身份词，如“受虐者”“调教者”“旧恋人”“同伴”“前战友”“上司”“后辈”。
3. 跳过普通剧情、普通外貌描写、单纯性交流水账；只保留有创意机制、调教结构、关系张力、道具/服装/心理机制的条目。
4. 每条必须能被改写进不同角色/世界观中，避免依赖原文具体事件。
5. 不要长篇引用原文；只能机制化概括。
6. 只输出 JSON 对象，不要 Markdown。"""

USER_TEMPLATE = """请从下面小说片段中广泛寻找成人向玩法候选。每段最多输出 {max_items} 条，宁可少但不要普通情节。不同条目之间要机制明确、不要重复。

{framework}

输出 JSON 格式：
{{
  "entries": [
    {{
      "title": "简洁玩法标题，不含分类前缀，不含人名",
      "trigger": "同 title",
      "source_span": "chunk {idx}/{total}, chars {start}-{end}",
      "creative_tags": ["2-5个机制标签"],
      "content": "简介：\\n【场景/玩法描述】...\\n\\n用法与交互细节：\\n1. ...\\n2. ...\\n3. ...\\n4. 可变体：..."
    }}
  ]
}}

小说片段：
<<<
{chunk}
>>>"""


def anonymize(text):
    for src, dst in NAME_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = re.sub(r"https?://\S+", "", text)
    return text


def safe_slug(text):
    text = re.sub(r"[\s/\\:：*?\"<>|]+", "_", text.strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] or "novel_extract"


def split_chunks(text, chunk_size, overlap):
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def call_deepseek(api_key, messages, max_tokens, temperature):
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            last_error = exc
            time.sleep(2 + attempt * 4)
    raise last_error


def parse_json_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def norm(text):
    return re.sub(r"[\s_：:、，,。\.\"“”《》【】{}（）()\-\—]+", "", text.lower())


def extract_one_chunk(api_key, idx, total, start, end, chunk, args):
    user_prompt = USER_TEMPLATE.format(
        max_items=args.max_items_per_chunk,
        framework=FRAMEWORK,
        idx=idx,
        total=total,
        start=start,
        end=end,
        chunk=chunk,
    )
    result = call_deepseek(
        api_key,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    obj = parse_json_object(result)
    cleaned = []
    for entry in obj.get("entries", []):
        title = anonymize(str(entry.get("title") or entry.get("trigger") or "").strip())
        if not title:
            continue
        title = re.sub(r"^(卷[一二三四五六七八九十]+[:：].*?[_-])", "", title)[:48]
        content = anonymize(str(entry.get("content", "")).strip())
        if not content or AGE_RISK_RE.search(title + content):
            continue
        tags = entry.get("creative_tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)]
        cleaned.append(
            {
                "title": title,
                "trigger": title,
                "source_span": str(entry.get("source_span") or f"chunk {idx}/{total}, chars {start}-{end}"),
                "creative_tags": [anonymize(str(tag))[:20] for tag in tags[:6] if str(tag).strip()],
                "content": content,
            }
        )
    return {"chunk": idx, "start": start, "end": end, "count": len(cleaned), "entries": cleaned}


def extract_raw(args, api_key, source, raw_out, checkpoint_out):
    raw_text = source.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    body = "\n".join(raw_text.splitlines()[10:])
    chunks = split_chunks(body, args.chunk_size, args.overlap)
    all_chunks = []
    all_entries = []
    print(f"extracting {len(chunks)} chunks with concurrency={args.concurrency}", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(extract_one_chunk, api_key, idx, len(chunks), start, end, chunk, args): idx
            for idx, (start, end, chunk) in enumerate(chunks, 1)
        }
        for future in as_completed(futures):
            result = future.result()
            all_chunks.append(result)
            all_entries.extend(result["entries"])
            checkpoint_out.write_text(
                json.dumps({"source": str(source), "chunks": sorted(all_chunks, key=lambda x: x["chunk"])}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"done chunk {result['chunk']}/{len(chunks)} entries={result['count']}", flush=True)

    seen = set()
    merged = []
    for entry in all_entries:
        signature = norm(entry["title"]) or norm(entry["content"][:80])
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(entry)

    entries_obj = {}
    for uid, entry in enumerate(merged, 1):
        entries_obj[str(uid)] = {
            "uid": uid,
            "key": [entry["trigger"]],
            "comment": entry["title"],
            "source_span": entry["source_span"],
            "creative_tags": entry["creative_tags"],
            "content": entry["content"],
        }
    raw = {
        "source": str(source),
        "extractor": "deepseek-chat",
        "classification_status": "raw_unclassified",
        "notes": "DeepSeek 只负责广泛提取候选；未写入卷名或子分类。已本地去重、匿名化，并过滤普通剧情和年龄感风险词。",
        "entries": entries_obj,
    }
    raw_out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.keep_checkpoint:
        checkpoint_out.unlink(missing_ok=True)
    return raw


def load_qr_module(project_root):
    script = project_root / "核心脚本" / "build_global_qr.py"
    spec = importlib.util.spec_from_file_location("build_global_qr", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_raw(raw, raw_path, classified_out, project_root):
    mod = load_qr_module(project_root)
    classified = {}
    counts = {}
    sub_counts = {}
    yuri_counts = {}
    tsf_counts = {}
    for key, entry in raw["entries"].items():
        title = entry.get("comment", "")
        content = entry.get("content", "")
        cat = mod.assign_category(title, content)
        subcat = mod.assign_subcategory(title, content, cat)
        yuri = mod.assign_yuri_index_subcategory(title, content)
        tsf = mod.assign_tsf_index_subcategory(title, content)
        if cat == mod.YURI_INDEX_CATEGORY and yuri:
            subcat = yuri
        if cat == mod.TSF_INDEX_CATEGORY and tsf:
            subcat = tsf
        counts[cat] = counts.get(cat, 0) + 1
        sub_counts.setdefault(cat, {})
        sub_counts[cat][subcat] = sub_counts[cat].get(subcat, 0) + 1
        if yuri:
            yuri_counts[yuri] = yuri_counts.get(yuri, 0) + 1
        if tsf:
            tsf_counts[tsf] = tsf_counts.get(tsf, 0) + 1
        item = dict(entry)
        item["category"] = cat
        item["subcategory"] = subcat
        if hasattr(mod, "make_structured_comment"):
            item["classified_comment"] = mod.make_structured_comment(cat, subcat, title)
        else:
            item["classified_comment"] = f"{subcat}_{title}"
        item["yuri_index_subcategory"] = yuri
        item["tsf_index_subcategory"] = tsf
        classified[key] = item

    out = {
        "source": raw.get("source"),
        "raw_file": str(raw_path),
        "classification_status": "classified_not_appended",
        "notes": "本文件只给 raw 候选打卷和子分类；尚未追加到世界书或快捷回复。",
        "counts": {
            "total": len(classified),
            "by_category": counts,
            "by_subcategory": sub_counts,
            "yuri_index": yuri_counts,
            "tsf_index": tsf_counts,
        },
        "entries": classified,
    }
    classified_out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def append_to_worldbook(classified, project_root, slug):
    product_dir = project_root / "成品" / "创意玩法知识网络"
    wb_path = product_dir / "极品调教大世界书_十二卷版.json"
    qr_path = product_dir / "极品调教快捷回复_十二卷无状态版.json"
    archive = product_dir / "归档" / f"{datetime.now().strftime('%Y%m%d')}_{slug}_入库前"
    archive.mkdir(parents=True, exist_ok=True)
    for path in [wb_path, qr_path, product_dir / "_极品调教大世界书_十二卷版.json"]:
        if path.exists():
            shutil.copy2(path, archive / path.name)

    wb = json.loads(wb_path.read_text(encoding="utf-8"))
    entries = wb["entries"]
    template_key = str(max(int(k) for k in entries if int(k) >= 100))
    template = copy.deepcopy(entries[template_key])
    existing_titles = {entry.get("key", [""])[0] for entry in entries.values() if entry.get("key")}
    next_uid = max(int(entry.get("uid", -1)) for entry in entries.values()) + 1
    first_uid = next_uid
    for raw_key in sorted(classified["entries"], key=lambda x: int(x)):
        item = classified["entries"][raw_key]
        title = item["comment"].strip()
        if title in existing_titles:
            title = f"{title}（{slug}提取）"
        content = item["content"].strip()
        if not content.startswith("{"):
            content = f"{{{title}}}\n" + content
        entry = copy.deepcopy(template)
        entry["uid"] = next_uid
        entry["displayIndex"] = next_uid
        entry["key"] = [title]
        entry["comment"] = item.get("classified_comment") or f"{item['subcategory']}_{title}"
        entry["content"] = content
        entries[str(next_uid)] = entry
        existing_titles.add(title)
        next_uid += 1
    wb["entries"] = dict(sorted(entries.items(), key=lambda kv: int(kv[0])))
    wb_path.write_text(json.dumps(wb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive, first_uid, next_uid - 1, len(classified["entries"])


def rebuild_qr(project_root):
    mod = load_qr_module(project_root)
    mod.main()


def validate_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--slug")
    parser.add_argument(
        "--project-root",
        default=DEFAULT_PROJECT_ROOT,
        help="Target project root, or set SILLYTAVERN_CREATIVE_ROOT.",
    )
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--chunk-size", type=int, default=10500)
    parser.add_argument("--overlap", type=int, default=900)
    parser.add_argument("--max-items-per-chunk", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=2600)
    parser.add_argument("--temperature", type=float, default=0.25)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--keep-checkpoint", action="store_true")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    if not args.project_root:
        raise SystemExit("missing --project-root (or set SILLYTAVERN_CREATIVE_ROOT)")
    project_root = Path(args.project_root).expanduser()
    out_dir = project_root / "资料源"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(args.slug or source.stem)
    raw_out = out_dir / f"{slug}_raw.json"
    classified_out = out_dir / f"{slug}_classified.json"
    checkpoint_out = out_dir / f"{slug}_deepseek_chunks.json"

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        api_key = getpass.getpass("DeepSeek API key: ").strip()
    if not api_key:
        raise SystemExit("missing DeepSeek API key")

    raw = extract_raw(args, api_key, source, raw_out, checkpoint_out)
    classified = classify_raw(raw, raw_out, classified_out, project_root)
    validate_json(raw_out)
    validate_json(classified_out)

    result = {
        "raw": str(raw_out),
        "classified": str(classified_out),
        "raw_entries": len(raw["entries"]),
        "classified_entries": len(classified["entries"]),
        "counts": classified["counts"],
    }

    if args.append:
        archive, first_uid, last_uid, added = append_to_worldbook(classified, project_root, slug)
        result.update({"archive": str(archive), "uid_range": f"{first_uid}-{last_uid}", "added": added})
    if args.rebuild:
        rebuild_qr(project_root)
        product_dir = project_root / "成品" / "创意玩法知识网络"
        validate_json(product_dir / "极品调教大世界书_十二卷版.json")
        validate_json(product_dir / "_极品调教大世界书_十二卷版.json")
        validate_json(product_dir / "极品调教快捷回复_十二卷无状态版.json")

    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
