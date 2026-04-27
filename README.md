# Feishu Clone

`feishu-clone` is an AI skill for cloning Feishu/Lark wiki or doc links into a new document. It uses `lark-cli docs +fetch` to read source XML, creates a new document, then appends the fetched blocks in batches.

## Install

Install the Feishu/Lark dependencies first:

```bash
npm install -g @larksuite/cli
npx -y -g skills add larksuite/cli
```

Then install this skill:

```bash
npx -y -g skills add https://github.com/wo0d/feishu-clone-skill.git
```

After updating either repository, run the corresponding `skills add` command again on each machine to refresh the installed skill files.

## Local Config

To preconfigure this skill on a machine, create a local config file from the example:

```bash
cp scripts/env.example scripts/.env
```

Then edit values as needed:

```bash
# LARK_DOC_CLONER_PREFERRED_IDENTITY=bot
# LARK_DOC_CLONER_OWNER_OPEN_ID=ou_xxxxxxxx
```

Leave values commented to trigger the first-run preference prompt. Uncomment them only if you want to preconfigure this machine.

When cloning as bot, ownership is transferred by default. Only set `LARK_DOC_CLONER_OWNER_OPEN_ID` when the current CLI user cannot be detected or you want to transfer ownership to a specific user.

## Usage

Run commands from this skill directory:

```bash
python3 scripts/clone_lark_doc.py --check-identities
python3 scripts/clone_lark_doc.py "https://example.feishu.cn/wiki/xxxxx" --as bot
```

Useful options:

- `--as user|bot`: choose the Lark identity explicitly.
- `--owner-open-id ou_xxx`: override the owner for bot-created clones. If omitted, the script transfers ownership to the current CLI user.
- `--name "New title"`: override the cloned document title.
- `--method export-import`: optional fallback when source export is allowed.

## Notes

- Do not commit `scripts/.env`; it may contain local identity preferences or personal `open_id` values.
- XML cloning is best effort. Comments, permissions, version history, and some embedded resources are not exact copies.
- For exact Drive-level copies, prefer `drive.files.copy` when source and target tokens are available.
