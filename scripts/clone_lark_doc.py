#!/usr/bin/env python3
"""Clone a Feishu/Lark wiki or doc URL via lark-cli.

默认使用 docs +fetch 读取 XML，再用 docs +create 重建文档，避免依赖源文档
导出权限。export/import 只作为可选路径保留。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REQUIRED_LARK_SKILLS = ("lark-shared", "lark-doc", "lark-drive", "lark-wiki")


def check_dependencies() -> None:
    missing: list[str] = []
    if not shutil.which("lark-cli"):
        missing.append("lark-cli")

    skills_root = Path.home() / ".agents" / "skills"
    missing_skills = [skill for skill in REQUIRED_LARK_SKILLS if not (skills_root / skill / "SKILL.md").exists()]
    if missing_skills:
        missing.append("official lark skills: " + ", ".join(missing_skills))

    if not missing:
        return

    raise RuntimeError(
        json.dumps(
            {
                "error": "Missing Feishu/Lark dependencies",
                "missing": missing,
                "install_commands": [
                    "npm install -g @larksuite/cli",
                    "npx -y skills add larksuite/cli -y -g",
                    "npx -y skills add https://github.com/wo0d/feishu-clone-skill.git -y -g",
                ],
                "note": "Install these dependencies yourself, or authorize the agent to install them, then retry.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def read_dotenv_value(key: str, env_file: Path = SCRIPT_DIR / ".env") -> str | None:
    if not env_file.exists():
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip().strip('"').strip("'")
        return value or None
    return None


def resolve_configured_owner_open_id(cli_value: str | None) -> tuple[str | None, str]:
    if cli_value:
        return cli_value, "provided"
    env_value = os.environ.get("LARK_DOC_CLONER_OWNER_OPEN_ID")
    if env_value:
        return env_value, "env"
    dotenv_value = read_dotenv_value("LARK_DOC_CLONER_OWNER_OPEN_ID")
    if dotenv_value:
        return dotenv_value, "scripts.env"
    return None, "none"


def check_available_identities() -> dict[str, Any]:
    """探测 bot / user 两种身份是否可用。

    bot 可用：auth status 成功返回且 appId 非空（app 已配置）。
    user 可用：auth status 的 note 字段中不含 "No user logged in"，
              或者 auth list 的输出不含 "No logged-in"。
    """
    available: list[str] = []
    details: dict[str, Any] = {}

    proc = subprocess.run(["lark-cli", "auth", "status"], text=True, capture_output=True)
    status_payload: dict[str, Any] = {}
    if proc.returncode == 0:
        try:
            status_payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            status_payload = {"raw_stdout": proc.stdout}

    # bot：app 已配置（有 appId）即可以 bot 身份调用
    if status_payload.get("appId"):
        available.append("bot")
        details["bot"] = {"available": True, "status": status_payload}
    else:
        details["bot"] = {"available": False, "status": status_payload, "stderr": proc.stderr.strip()}

    # user：auth list 输出不含 "No logged-in" 说明有用户已登录
    list_proc = subprocess.run(["lark-cli", "auth", "list"], text=True, capture_output=True)
    list_output = (list_proc.stdout + list_proc.stderr).strip()
    no_user_note = "No user logged in" in status_payload.get("note", "")
    no_user_list = "No logged-in" in list_output
    if list_proc.returncode == 0 and not no_user_note and not no_user_list:
        available.append("user")
        details["user"] = {"available": True, "list_output": list_output}
    else:
        details["user"] = {
            "available": False,
            "note": "No user logged in. Run `lark-cli auth login` to enable user identity.",
        }

    return {"available_identities": available, "details": details}


def resolve_identity(requested: str) -> str:
    if requested != "auto":
        return requested

    proc = subprocess.run(["lark-cli", "auth", "status"], text=True, capture_output=True)
    if proc.returncode == 0:
        try:
            status = json.loads(proc.stdout)
        except json.JSONDecodeError:
            status = {}
        if status.get("identity") == "bot":
            return "bot"

    return "user"


def find_key(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        for item in payload.values():
            found = find_key(item, key)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_key(item, key)
            if found:
                return found
    return None


def get_current_user_open_id() -> tuple[str | None, dict[str, Any] | None]:
    cmd = ["lark-cli", "contact", "+get-user", "--as", "user", "--format", "json"]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        return None, parse_cli_failure(cmd, proc)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, {"error": "Invalid JSON from contact +get-user", "stdout": proc.stdout, "stderr": proc.stderr}
    return find_key(payload, "open_id"), payload


def resolve_bot_owner_open_id(cli_value: str | None, identity: str) -> tuple[str | None, str, dict[str, Any] | None]:
    if identity != "bot":
        return None, "not_bot", None

    configured_open_id, source = resolve_configured_owner_open_id(cli_value)
    if configured_open_id:
        return configured_open_id, source, None

    open_id, user_lookup = get_current_user_open_id()
    if open_id:
        return open_id, "current_user", user_lookup
    return None, "none", user_lookup


def transfer_owner_to_open_id(doc_token: str, identity: str, owner_open_id: str | None) -> dict[str, Any]:
    if not owner_open_id:
        return {"status": "skipped", "reason": "no owner_open_id provided"}
    if identity != "bot":
        return {"status": "skipped", "reason": "document was not created with bot identity"}

    cmd = [
        "lark-cli",
        "drive",
        "permission.members",
        "transfer_owner",
        "--as",
        "bot",
        "--params",
        json.dumps(
            {
                "token": doc_token,
                "type": "docx",
                "remove_old_owner": False,
                "old_owner_perm": "full_access",
                "stay_put": False,
            },
            ensure_ascii=False,
        ),
        "--data",
        json.dumps({"member_type": "openid", "member_id": owner_open_id}, ensure_ascii=False),
        "--format",
        "json",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        return {"status": "failed", "open_id": owner_open_id, "error": parse_cli_failure(cmd, proc)}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"raw_stdout": proc.stdout, "stderr": proc.stderr}
    return {"status": "ok", "open_id": owner_open_id, "result": payload}


def run_json(cmd: list[str], cwd: Path | None = None) -> dict[str, Any]:
    """运行 lark-cli 并解析 JSON 输出。"""
    proc = subprocess.run(cmd, text=True, capture_output=True, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(parse_cli_failure(cmd, proc), ensure_ascii=False, indent=2))
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "command": cmd,
                    "error": f"Invalid JSON output: {exc}",
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from exc


def parse_cli_failure(cmd: list[str], proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    for stream in (proc.stderr, proc.stdout):
        try:
            parsed = json.loads(stream)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break

    result: dict[str, Any] = {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if payload:
        result["parsed_error"] = payload
        error = payload.get("error", {})
        if isinstance(error, dict):
            result["required_scope"] = extract_required_scope(error.get("message", ""))
            if error.get("console_url"):
                result["console_url"] = error["console_url"]
            if error.get("hint"):
                result["hint"] = error["hint"]
    elif "need_user_authorization" in proc.stderr:
        result["hint"] = "Run lark-cli auth login with the exact scopes needed for docs fetch/export/import, then retry with --as user."
    return result


def extract_required_scope(message: str) -> str | None:
    match = re.search(r"required scope ([\w:.-]+)", message)
    return match.group(1) if match else None


def fetch_source(source: str, identity: str) -> dict[str, Any]:
    return run_json(
        [
            "lark-cli",
            "docs",
            "+fetch",
            "--api-version",
            "v2",
            "--doc",
            source,
            "--as",
            identity,
            "--format",
            "json",
        ]
    )


def create_from_xml(content_file: Path, identity: str, parent_token: str | None, parent_position: str | None) -> dict[str, Any]:
    cmd = [
        "lark-cli",
        "docs",
        "+create",
        "--api-version",
        "v2",
        "--doc-format",
        "xml",
        "--content",
        f"@{content_file.name}",
        "--as",
        identity,
    ]
    if parent_token:
        cmd.extend(["--parent-token", parent_token])
    if parent_position:
        cmd.extend(["--parent-position", parent_position])
    return run_json(cmd, cwd=content_file.parent)


def append_xml(doc: str, content_file: Path, identity: str) -> dict[str, Any]:
    cmd = [
        "lark-cli",
        "docs",
        "+update",
        "--api-version",
        "v2",
        "--doc-format",
        "xml",
        "--command",
        "append",
        "--doc",
        doc,
        "--content",
        f"@{content_file.name}",
        "--as",
        identity,
    ]
    return run_json(cmd, cwd=content_file.parent)


def replace_title(content: str, new_title: str | None) -> str:
    if not new_title:
        return content
    escaped = html.escape(new_title, quote=False)
    if re.search(r"<title>.*?</title>", content, flags=re.S):
        return re.sub(r"<title>.*?</title>", f"<title>{escaped}</title>", content, count=1, flags=re.S)
    return f"<title>{escaped}</title>\n{content}"


def split_top_level_blocks(content: str) -> tuple[str, list[str]]:
    root = ET.fromstring(f"<root>{content}</root>")
    title = "Untitled Lark document"
    blocks: list[str] = []
    for child in list(root):
        text = ET.tostring(child, encoding="unicode", method="xml")
        if child.tag == "title":
            title = re.sub(r"<[^>]+>", "", text).strip() or title
            continue
        blocks.append(text)
    return html.unescape(title), blocks


def chunk_blocks(blocks: list[str], max_chars: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for block in blocks:
        block_len = len(block)
        if current and current_len + block_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(block)
        current_len += block_len
    if current:
        chunks.append(current)
    return chunks


def find_doc_ref(payload: Any) -> str | None:
    if isinstance(payload, dict):
        preferred_keys = ("document_id", "doc_token", "token", "url")
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = find_doc_ref(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_doc_ref(value)
            if found:
                return found
    return None


def find_document_url(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("url")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        for value in payload.values():
            found = find_document_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_document_url(value)
            if found:
                return found
    return None


def append_blocks_with_retry(
    doc: str,
    blocks: list[str],
    identity: str,
    output_dir: Path,
    max_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    append_results: list[dict[str, Any]] = []
    failed_blocks: list[dict[str, Any]] = []

    def append_group(group: list[str], label: str) -> None:
        chunk_file = output_dir / f"{label}.xml"
        chunk_file.write_text("".join(group), encoding="utf-8")
        try:
            result = append_xml(doc, chunk_file, identity)
            append_results.append({"label": label, "blocks": len(group), "chars": sum(len(item) for item in group), "result": result})
        except Exception as exc:
            if len(group) == 1:
                failed_blocks.append({"label": label, "chars": len(group[0]), "error": str(exc), "content_preview": group[0][:500]})
                return
            midpoint = len(group) // 2
            append_group(group[:midpoint], f"{label}a")
            append_group(group[midpoint:], f"{label}b")

    for index, chunk in enumerate(chunk_blocks(blocks, max_chars), start=1):
        append_group(chunk, f"chunk-{index:04d}")
    return append_results, failed_blocks


def extract_title(content: str, fallback: str) -> str:
    match = re.search(r"<title>(.*?)</title>", content, flags=re.S)
    if not match:
        return fallback
    title = re.sub(r"<[^>]+>", "", match.group(1))
    title = html.unescape(title).strip()
    return title or fallback


def find_new_docx(output_dir: Path, before: set[Path]) -> Path:
    candidates = sorted(
        [path for path in output_dir.glob("*.docx") if path not in before],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    candidates = sorted(output_dir.glob("*.docx"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    raise RuntimeError(f"No .docx file found in export directory: {output_dir}")


def export_docx(document_id: str, identity: str, output_dir: Path) -> tuple[str, dict[str, Any], Path]:
    last_error: str | None = None
    for doc_type in ("docx", "doc"):
        before = set(output_dir.glob("*.docx"))
        cmd = [
            "lark-cli",
            "drive",
            "+export",
            "--token",
            document_id,
            "--doc-type",
            doc_type,
            "--file-extension",
            "docx",
            "--output-dir",
            str(output_dir),
            "--overwrite",
            "--as",
            identity,
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            failure = parse_cli_failure(cmd, proc)
            failure["doc_type"] = doc_type
            last_error = json.dumps(failure, ensure_ascii=False, indent=2)
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": proc.stdout}
        exported_file = find_new_docx(output_dir, before)
        return doc_type, payload, exported_file
    raise RuntimeError(last_error or "Export failed for both docx and doc source types")


def import_docx(file_path: Path, identity: str, name: str, folder_token: str | None) -> dict[str, Any]:
    cmd = [
        "lark-cli",
        "drive",
        "+import",
        "--file",
        str(file_path),
        "--type",
        "docx",
        "--name",
        name,
        "--as",
        identity,
    ]
    if folder_token:
        cmd.extend(["--folder-token", folder_token])
    return run_json(cmd)


def clone_by_xml(
    source: str,
    identity: str,
    name: str | None,
    parent_token: str | None,
    parent_position: str | None,
    owner_open_id: str | None,
    output_dir: Path,
) -> dict[str, Any]:
    fetched = fetch_source(source, identity)
    document = fetched.get("data", {}).get("document", {})
    document_id = document.get("document_id")
    content = document.get("content", "")
    if not document_id or not content:
        raise RuntimeError(json.dumps({"error": "No data.document.document_id/content in fetch result", "fetch": fetched}, ensure_ascii=False))

    source_title, blocks = split_top_level_blocks(content)
    clone_name = name or f"{source_title} - copy"
    full_content = replace_title(content, clone_name)
    full_content_file = output_dir / "clone-content.xml"
    full_content_file.write_text(full_content, encoding="utf-8")

    seed_file = output_dir / "seed-title.xml"
    seed_file.write_text(f"<title>{html.escape(clone_name, quote=False)}</title><p></p>", encoding="utf-8")
    create_result = create_from_xml(seed_file, identity, parent_token, parent_position)
    doc_ref = find_doc_ref(create_result)
    if not doc_ref:
        raise RuntimeError(json.dumps({"error": "Could not find new document token/url in create result", "create_result": create_result}, ensure_ascii=False))

    append_results, failed_blocks = append_blocks_with_retry(doc_ref, blocks, identity, output_dir, max_chars=9000)
    owner_transfer = transfer_owner_to_open_id(doc_ref, identity, owner_open_id)
    ownership_policy = (
        {
            "mode": "transfer_owner",
            "reason": "bot-created documents default to ownership transfer; no separate permission grant was attempted",
            "owner_transfer": owner_transfer,
        }
        if identity == "bot"
        else {"mode": "not_applicable", "reason": "document was created with user identity"}
    )

    return {
        "ok": True,
        "method": "xml-create",
        "source": source,
        "source_document_id": document_id,
        "source_title": source_title,
        "clone_name": clone_name,
        "doc_ref": doc_ref,
        "document_url": find_document_url(create_result),
        "owner_transfer": owner_transfer,
        "ownership_policy": ownership_policy,
        "content_file": str(full_content_file),
        "seed_file": str(seed_file),
        "create_result": create_result,
        "append_batches": len(append_results),
        "failed_blocks": failed_blocks,
        "notices": collect_notice(fetched, create_result),
        "limitations": [
            "This path does not need source export permission.",
            "Comments, version history, permissions, and wiki tree position are not cloned.",
            "Embedded media and resource blocks are preserved only when Lark docs +create accepts the fetched XML tokens.",
        ],
    }


def clone_by_export(
    source: str,
    identity: str,
    name: str | None,
    folder_token: str | None,
    owner_open_id: str | None,
    output_dir: Path,
) -> dict[str, Any]:
    fetched = fetch_source(source, identity)
    document = fetched.get("data", {}).get("document", {})
    document_id = document.get("document_id")
    content = document.get("content", "")
    if not document_id:
        raise RuntimeError(json.dumps({"error": "No data.document.document_id in fetch result", "fetch": fetched}, ensure_ascii=False))

    source_title = extract_title(content, "Untitled Lark document")
    clone_name = name or f"{source_title} - copy"
    export_type, export_result, exported_file = export_docx(document_id, identity, output_dir)
    import_result = import_docx(exported_file, identity, clone_name, folder_token)
    doc_ref = find_doc_ref(import_result)
    owner_transfer = transfer_owner_to_open_id(doc_ref or "", identity, owner_open_id) if doc_ref else {
        "status": "skipped",
        "reason": "could not find imported document token/url in import result",
    }
    ownership_policy = (
        {
            "mode": "transfer_owner",
            "reason": "bot-created documents default to ownership transfer",
            "owner_transfer": owner_transfer,
        }
        if identity == "bot"
        else {"mode": "not_applicable", "reason": "document was created with user identity"}
    )

    return {
        "ok": True,
        "method": "export-import",
        "source": source,
        "source_document_id": document_id,
        "source_title": source_title,
        "clone_name": clone_name,
        "export_type": export_type,
        "exported_file": str(exported_file),
        "doc_ref": doc_ref,
        "document_url": find_document_url(import_result),
        "owner_transfer": owner_transfer,
        "ownership_policy": ownership_policy,
        "import_result": import_result,
        "notices": collect_notice(fetched, export_result, import_result),
        "limitations": [
            "This path requires source export permission.",
            "Comments, version history, permissions, and wiki tree position are not cloned.",
            "Live embedded sheets, bitables, whiteboards, or unsupported media may be flattened or represented differently after export/import.",
        ],
    }


def collect_notice(*payloads: dict[str, Any]) -> list[Any]:
    notices: list[Any] = []
    for payload in payloads:
        notice = payload.get("_notice")
        if notice:
            notices.append(notice)
    return notices


def main() -> int:
    parser = argparse.ArgumentParser(description="Clone a Feishu/Lark wiki or doc URL into a new Lark Docx.")
    parser.add_argument("source", nargs="?", default=None, help="Feishu/Lark wiki/doc URL or token")
    parser.add_argument("--check-identities", action="store_true", help="探测可用的 lark-cli 身份后退出，不执行克隆")
    parser.add_argument("--name", help="Name of the cloned document")
    parser.add_argument("--parent-token", help="Target parent folder or wiki-node token for docs +create")
    parser.add_argument("--parent-position", help="Parent position for docs +create, e.g. my_library")
    parser.add_argument("--folder-token", help="Target Drive folder token for --method export-import")
    parser.add_argument("--as", dest="identity", choices=["auto", "user", "bot"], default="auto", help="Lark identity. auto uses bot when current CLI identity is bot, otherwise user.")
    parser.add_argument("--owner-open-id", help="Open ID to receive ownership when the document is created by bot. Fallbacks: LARK_DOC_CLONER_OWNER_OPEN_ID env var, scripts/.env, then current CLI user.")
    parser.add_argument(
        "--method",
        choices=["xml-create", "export-import"],
        default="xml-create",
        help="Clone strategy. Default avoids source export permission.",
    )
    parser.add_argument("--workdir", help="Directory for exported docx; defaults to a temporary directory")
    parser.add_argument("--keep-workdir", action="store_true", help="Keep temporary export directory")
    args = parser.parse_args()

    temp_dir: str | None = None
    output_dir = Path(args.workdir).expanduser().resolve() if args.workdir else Path(tempfile.gettempdir())

    try:
        check_dependencies()

        if args.workdir:
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            temp_dir = tempfile.mkdtemp(prefix="lark-doc-clone-")
            output_dir = Path(temp_dir)

        if args.check_identities:
            result = check_available_identities()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not args.source:
            parser.error("source is required unless --check-identities is used")
        identity = resolve_identity(args.identity)
        owner_open_id, owner_open_id_source, owner_user_lookup = resolve_bot_owner_open_id(args.owner_open_id, identity)
        if args.method == "xml-create":
            result = clone_by_xml(args.source, identity, args.name, args.parent_token, args.parent_position, owner_open_id, output_dir)
        else:
            result = clone_by_export(args.source, identity, args.name, args.folder_token, owner_open_id, output_dir)
        result["requested_identity"] = args.identity
        result["identity"] = identity
        result["owner_open_id_source"] = owner_open_id_source
        if owner_user_lookup is not None:
            result["owner_user_lookup"] = owner_user_lookup
        result["workdir"] = str(output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        try:
            error: Any = json.loads(str(exc))
        except json.JSONDecodeError:
            error = str(exc)
        print(json.dumps({"ok": False, "error": error, "workdir": str(output_dir)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        if temp_dir and not args.keep_workdir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
