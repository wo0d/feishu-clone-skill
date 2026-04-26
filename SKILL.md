---
name: feishu-clone
description: Clone Feishu/Lark wiki or doc links into a new document without relying on source export permission. Use when the user asks to 复刻、复制、克隆、另存为、搬运、备份 a Feishu/Lark Wiki node or Doc/Docx document from a URL into their own cloud document, preserving the fetched XML structure and embedded media tokens as much as Lark docs create/update APIs allow, and optionally transferring bot-created document ownership to a configured owner open_id.
---

# Feishu Clone

## Core Rule

Do not default to Drive export/import. Many source documents disable export at the document-owner permission layer, so export can fail even when app scopes are correct.

Default to this path:

1. Fetch source XML with `lark-cli docs +fetch --api-version v2`.
2. Create a new title-only document with `lark-cli docs +create --api-version v2 --doc-format xml`.
3. Parse the fetched XML into top-level blocks and append them in batches with `docs +update --command append`.
4. If one batch fails, split it and retry; if one block still fails, record that block and continue.

This path only needs readable source content plus permission to create a new document. It does not require source export permission.

## Required Companion Skills

Read these before running live operations:

- `lark-shared` for authentication, identity, scopes, and permission errors.
- `lark-doc` for `docs +fetch`, `docs +create`, and `docs +update`.
- `lark-drive` only when importing local files, using Drive-level copy, or handling permissions.
- `lark-wiki` only when the target is a wiki node/space or source wiki node metadata is needed.

## Interactive Pre-Clone Flow

**MANDATORY: Always execute these steps before running the clone script. Never skip to the Fast Path directly.**

### Step 1 — Check saved preferences

Read `scripts/.env` in this skill directory and look for:

- `LARK_DOC_CLONER_PREFERRED_IDENTITY` — `bot` or `user`
- `LARK_DOC_CLONER_TRANSFER_OWNERSHIP` — `true` or `false`
- `LARK_DOC_CLONER_OWNER_OPEN_ID` — the user's `open_id`

**If all required keys are present** (identity + transfer preference, and `open_id` when transfer is `true`):
→ Skip to Step 3 directly. No questions needed.

**If any required key is missing**:
→ Continue to Step 2 to ask the user once.

### Step 2 — Ask once, save permanently

Run identity detection first:

```bash
python3 scripts/clone_lark_doc.py --check-identities
```

Then ask the user **a single combined question** based on what's missing and what identities are available. Examples:

**Both bot and user available, no prefs saved:**
> 复刻前需要确认几个偏好（之后不再询问）：
>
> 1. 使用哪个身份？**user**（所有权直接属于您）/ **bot**（机器人创建）
> 2. 若选 bot：是否转移文档所有权给您？（是 / 否）
>
> 示例回复：「bot，是」或「user」

**Only bot available, no prefs saved:**
> 当前只有 **bot** 身份可用，是否需要将复刻后的文档所有权转移给您？（是 / 否）
> 您的选择将被记住，下次不再询问。

After the user replies, handle `open_id` if needed:

- Transfer = yes AND `LARK_DOC_CLONER_OWNER_OPEN_ID` missing:
  > 还需要您的飞书 `open_id`（格式：`ou_xxxxxxxx`）以完成所有权转移，之后也不再询问。
  Wait for user to provide it.

Once all answers are collected, **write them to `scripts/.env`** using the Edit tool (append or update, never overwrite existing unrelated lines):

```
LARK_DOC_CLONER_PREFERRED_IDENTITY=bot
LARK_DOC_CLONER_TRANSFER_OWNERSHIP=true
LARK_DOC_CLONER_OWNER_OPEN_ID=ou_xxxxxxxx
```

### Step 3 — Run the clone

Build the command from saved (or just-collected) preferences:

- `LARK_DOC_CLONER_PREFERRED_IDENTITY=user` → `--as user`
- `LARK_DOC_CLONER_PREFERRED_IDENTITY=bot` + `LARK_DOC_CLONER_TRANSFER_OWNERSHIP=true` → `--as bot --owner-open-id <LARK_DOC_CLONER_OWNER_OPEN_ID>`
- `LARK_DOC_CLONER_PREFERRED_IDENTITY=bot` + `LARK_DOC_CLONER_TRANSFER_OWNERSHIP=false` → `--as bot`

Then run it per the Fast Path below.

---

## Fast Path

After completing the Interactive Pre-Clone Flow above, run the bundled script with the confirmed options. Always pass `--as` explicitly; never use `auto` after the interactive flow has determined the identity.

```bash
python3 scripts/clone_lark_doc.py \
  "https://example.feishu.cn/wiki/xxxxx" \
  --as user|bot \
  [--owner-open-id ou_xxx]
```

Useful options:

- `--as user|bot`: always set explicitly based on the user's choice in the Interactive Pre-Clone Flow.
- `--owner-open-id ou_xxx`: pass only when user confirmed ownership transfer and `open_id` is available. Fallback order: command-line flag → `LARK_DOC_CLONER_OWNER_OPEN_ID` env var → `scripts/.env`.
- `--check-identities`: detect which identities (bot/user) are currently logged in without running a clone. Used in Step 1 of the Interactive Pre-Clone Flow.
- `--name "New title"`: replace the cloned document `<title>`.
- `--parent-token <token>`: create under a target folder or wiki node (xml-create path).
- `--parent-position my_library`: create under the current identity's personal wiki library when supported (xml-create path).
- `--folder-token <token>`: target Drive folder for `--method export-import`.
- `--workdir <path>`: use a custom directory instead of a temp dir; directory is kept after the run.
- `--keep-workdir`: keep the auto-created temp directory after the run (for debugging).
- `--method export-import`: optional fallback only when export is allowed.

The script prints JSON with the source document ID, source title, create result, work directory, and known fidelity limits.

For long documents, the script intentionally avoids one giant create request because Lark can time out. It creates the title first, then appends batches.

After a successful run, always extract and send the user the new document link from the top-level `document_url` field. If `document_url` is empty, inspect `create_result.data.document.url` or `import_result` for the URL. Do not finish with only a token.

If the clone was created with bot identity and `--owner-open-id` was provided, inspect `owner_transfer`:

- `status: ok`: ownership was transferred to the provided `open_id`.
- `status: failed`: report the transfer error, but keep the clone result and URL.
- `status: skipped`: explain why ownership transfer was not attempted.

If the clone was created with bot identity and no `--owner-open-id` was provided, inspect `permission_grant_to_current_user`:

- `status: ok`: current CLI user was added with `full_access`.
- `status: skipped`: explain why, usually no user login/open_id is available.
- `status: failed`: report the permission error, but keep the clone result and URL.

## Manual XML Workflow

1. Fetch the source:

```bash
lark-cli docs +fetch \
  --api-version v2 \
  --doc "<source-url>" \
  --as bot \
  --format json
```

2. Save `data.document.content` into a local `.xml` file. If the user wants a new title, replace only the first `<title>...</title>`.

3. Create the clone:

```bash
cd /tmp/lark-doc-clone
lark-cli docs +create \
  --api-version v2 \
  --doc-format xml \
  --content "@clone-content.xml" \
  --as bot
```

`--content @file` must use a path relative to the current directory; do not pass an absolute `@/tmp/...` path.

Add `--parent-token "<token>"` or `--parent-position my_library` only when the user asks for a target location.

## Media And Resource Blocks

The fetched XML can contain image/video/file/resource tokens such as `<img src="...">`, `<figure><source token="...">`, `<sheet token="...">`, or `<bitable token="...">`.

Keep these tokens in the first clone attempt. Lark's document create API may preserve them when the current identity can access the resources. If create fails because of media/resource tokens:

1. Retry after removing unsupported media/resource blocks, preserving surrounding text and tables.
2. For images that must be retained, use `docs +media-download` on the source token and `docs +media-insert` into the new document, but expect placement to be less exact.
3. For embedded sheets/bitables, clone or reference them separately with `lark-sheets` or `lark-base`; do not pretend the live object was cloned unless it was.

## Optional Export/Import

Use export/import only when source export is explicitly allowed or the XML path cannot represent the document well enough:

```bash
python3 scripts/clone_lark_doc.py \
  "<source-url>" \
  --method export-import \
  --as bot
```

If export fails with a document-owner export restriction, stop using this path and return to XML clone. Do not tell the user that app scopes alone will solve owner-level export restrictions.

## Drive-Level Exact Copy

If the user has a source Drive file token, target folder token, and wants a Drive-level copy, use `drive.files.copy`. This may be more exact but requires real folder token and source type:

```bash
lark-cli schema drive.files.copy
lark-cli drive files copy \
  --params '{"file_token":"<source-file-token>"}' \
  --data '{"folder_token":"<target-folder-token>","name":"<new-name>","type":"docx"}'
```

Do not guess file type or target folder token.

## Permission Handling

If `--as user` returns `need_user_authorization`, start scoped login with the exact scope reported by CLI. If no exact scope is reported, try the smallest relevant docs create/read scope first.

If `--as bot` returns missing scope, give the user the `console_url`. Do not run `auth login` for bot.

When bot creates the document, add current user management permission with:

```bash
lark-cli contact +get-user --as user --format json
lark-cli drive permission.members create \
  --as bot \
  --params '{"token":"<new_doc_token>","type":"docx","need_notification":false}' \
  --data '{"member_type":"openid","member_id":"<current_user_open_id>","perm":"full_access","type":"user"}'
```

This grant is best-effort. If user identity is not logged in, report the skipped grant and still provide the created document URL.

If the user provides an `open_id` and wants delete/owner-level control, transfer ownership instead of only adding `full_access`:

```bash
lark-cli drive permission.members transfer_owner \
  --as bot \
  --params '{"token":"<new_doc_token>","type":"docx","remove_old_owner":false,"old_owner_perm":"full_access","stay_put":false}' \
  --data '{"member_type":"openid","member_id":"<owner_open_id>"}'
```

The script does this automatically when `--owner-open-id` or `LARK_DOC_CLONER_OWNER_OPEN_ID` is set.

Optional `.env` file next to the script:

```bash
# scripts/.env
LARK_DOC_CLONER_OWNER_OPEN_ID=ou_xxx
```

Only store non-secret defaults such as `open_id` here. Do not put app secrets or access tokens in this file.

## Quality Check

After cloning, report:

- New document URL from `document_url` or the create/import result. This is mandatory.
- Whether the method was `xml-create` or `export-import`.
- Which identity was used, whether ownership transfer succeeded when `--owner-open-id` was provided, or whether current-user `full_access` was granted when bot created the document.
- Whether media/resource blocks may need manual inspection.
- Known non-cloned items: comments, permissions, revision history, source wiki tree position, and possibly live embedded app state.

Never complete a clone task without giving the user the newly created Feishu document link.
