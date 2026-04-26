# Clone Fidelity Limits

Prefer the term "clone" for a best-effort duplicate, not a byte-for-byte copy.

The default XML create/update path usually preserves:

- document title
- headings and paragraphs
- tables
- many images and media/resource tokens when the creating identity can access them
- basic formatting represented in fetched Lark XML

It usually does not preserve:

- source permissions and collaborators
- comments and comment threads
- edit history and revision IDs
- wiki node location and tree hierarchy
- live behavior of embedded sheets, bitables, whiteboards, mindnotes, synced blocks, and some media

Drive export/import is optional only when source export is allowed. Many source documents block export at the owner permission layer.

If the user needs an exact Drive-level copy and has a target folder token, prefer `drive.files.copy`.
