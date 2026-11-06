#!/usr/bin/env python3
"""把 Clash 纯文本规则列表 (.list) 编译成 sing-box 二进制规则集 (.srs)。

sing-box 不能直接读取 Clash 的 .list，因此需要两步：先把行式规则转成
sing-box source JSON，再调用 `sing-box rule-set compile` 编译成二进制。

用法:
    python3 scripts/clash2srs.py MyDirect.list MyProxy.list

每个输入 X.list 会在同目录生成 X.srs。需要 PATH 中存在 sing-box (>= 1.8)，
也可以用 --singbox 指定可执行文件路径。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

# Clash 规则类型 -> sing-box headless rule 字段
RULE_MAP = {
    "DOMAIN": "domain",
    "DOMAIN-SUFFIX": "domain_suffix",
    "DOMAIN-KEYWORD": "domain_keyword",
    "DOMAIN-REGEX": "domain_regex",
    "IP-CIDR": "ip_cidr",
    "IP-CIDR6": "ip_cidr",
    "SRC-IP-CIDR": "source_ip_cidr",
    "DST-PORT": "port",
    "SRC-PORT": "source_port",
    "PROCESS-NAME": "process_name",
    "PROCESS-PATH": "process_path",
}

# 规则集层面没有对应字段：要么属于 route 层，要么依赖外部数据源
UNSUPPORTED = {
    "MATCH",
    "FINAL",
    "GEOIP",
    "SRC-GEOIP",
    "GEOSITE",
    "RULE-SET",
    "IP-ASN",
    "SCRIPT",
    "SUB-RULE",
    "NETWORK",
}

DOMAIN_FIELDS = {"domain", "domain_suffix", "domain_keyword"}

# 固定的输出顺序，保证多次生成结果一致、diff 稳定
FIELD_ORDER = [
    "domain",
    "domain_suffix",
    "domain_keyword",
    "domain_regex",
    "ip_cidr",
    "source_ip_cidr",
    "port",
    "source_port",
    "process_name",
    "process_path",
]


def warn(message: str) -> None:
    print(f"警告: {message}", file=sys.stderr)


def parse_list(path: Path) -> dict[str, dict[str, None]]:
    """解析 Clash 规则列表，按 sing-box 字段归集，保留出现顺序并去重。"""
    buckets: dict[str, dict[str, None]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = [part.strip() for part in line.split(",")]
        rule_type = parts[0].upper()
        if rule_type in UNSUPPORTED:
            warn(f"{path}:{lineno} 规则集不支持 {rule_type}，已跳过: {line}")
            continue
        field = RULE_MAP.get(rule_type)
        if field is None:
            warn(f"{path}:{lineno} 未知规则类型 {rule_type}，已跳过: {line}")
            continue
        if len(parts) < 2 or not parts[1]:
            warn(f"{path}:{lineno} 缺少规则内容，已跳过: {line}")
            continue
        value = parts[1].lower() if field in DOMAIN_FIELDS else parts[1]
        # 第三个字段（策略名 / no-resolve）在规则集里没有意义，直接忽略
        buckets.setdefault(field, {})[value] = None
    return buckets


def build_source(buckets: dict[str, dict[str, None]], version: int) -> dict:
    rules = []
    for field in FIELD_ORDER:
        values = buckets.get(field)
        if values:
            rules.append({field: list(values)})
    return {"version": version, "rules": rules}


def compile_rule_set(singbox: str, source_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            singbox,
            "rule-set",
            "compile",
            "--output",
            str(output_path),
            str(source_path),
        ],
        check=True,
    )


def fail(message: str) -> NoReturn:
    print(f"错误: {message}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 Clash 纯文本规则列表编译成 sing-box 二进制规则集 (.srs)"
    )
    parser.add_argument("inputs", nargs="+", type=Path, metavar="FILE.list")
    parser.add_argument(
        "--singbox",
        default="sing-box",
        help="sing-box 可执行文件路径（默认从 PATH 查找）",
    )
    parser.add_argument(
        "--rule-set-version",
        type=int,
        default=1,
        choices=range(1, 6),
        metavar="N",
        help="生成的规则集版本号，默认 1（sing-box >= 1.8 均可读取）",
    )
    parser.add_argument(
        "--keep-json",
        action="store_true",
        help="同时保留中间 source JSON（调试用）",
    )
    args = parser.parse_args(argv)

    singbox = shutil.which(args.singbox)
    if singbox is None:
        fail(f"找不到 sing-box 可执行文件: {args.singbox}")

    failed = 0
    for list_path in args.inputs:
        if not list_path.is_file():
            print(f"错误: 文件不存在: {list_path}", file=sys.stderr)
            failed += 1
            continue

        buckets = parse_list(list_path)
        total = sum(len(values) for values in buckets.values())
        if total == 0:
            print(f"错误: {list_path} 没有可识别的规则", file=sys.stderr)
            failed += 1
            continue

        source = build_source(buckets, args.rule_set_version)
        output_path = list_path.with_suffix(".srs")
        tmpdir: tempfile.TemporaryDirectory | None = None
        if args.keep_json:
            json_path = list_path.with_suffix(".json")
        else:
            tmpdir = tempfile.TemporaryDirectory()
            json_path = Path(tmpdir.name) / f"{list_path.stem}.json"
        json_path.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        try:
            compile_rule_set(singbox, json_path, output_path)
        except subprocess.CalledProcessError as exc:
            print(
                f"错误: 编译 {list_path} 失败（sing-box 退出码 {exc.returncode}）",
                file=sys.stderr,
            )
            failed += 1
            continue
        finally:
            if tmpdir is not None:
                tmpdir.cleanup()

        print(f"{list_path} -> {output_path} ({output_path.stat().st_size} 字节)")
        for field in FIELD_ORDER:
            values = buckets.get(field)
            if values:
                print(f"  {field}: {len(values)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
