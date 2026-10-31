
# /kb-l3-fix — repair the structure of L3 from drafts

You repair the layout of L3 (the `.raw.md` chapter files) of one ingested
document: wrong heading ids, fallback ids, broken paragraphs, repeated
blocks, page headers and footers left in the text. You do it by writing
drafts. `kb l3 fix apply` checks every draft against the source PDF and
writes only the ones that pass. You never write into `.kb/` yourself, and a
human still confirms the result.

<HARD-RULE>
1. Run only when `.kb/config.yaml` has `l3_fix:` with `enabled: true`. If it
   does not, say "L3 fix is off — a person must run `kb l3 fix on` first" and
   stop. Never turn the switch on yourself.
2. Write drafts only. NEVER edit `.kb/<doc-id>/*.raw.md`, `*.md`,
   `_manifest.yaml`, `_l3fix.yaml` or `_l3check.yaml` directly. Only
   `kb l3 fix apply` changes L3, and a direct edit is caught by the gate
   anyway.
3. NEVER run `kb l3 confirm`. Only a human confirms.
4. The text must stay the PDF's text. Do not add, reword, translate,
   summarize, fix spelling or "clean up" anything. A word may enter L3 only
   where the PDF has that word in that place.
5. Never change a table: same table blocks, byte for byte, same order.
6. Retry a rejected draft at most 2 times, then stop on that section and
   leave it for the human.
</HARD-RULE>

Docker: when `docker info` succeeds and `docker-compose.yml` exists, prefix
every `kb` command below with `docker compose run --rm hub`.

## Workflow

1. **Pick the document and the PDF.** The user names a document id (ask if
   they did not). The PDF is the file it was ingested from, normally
   `source/<file>.pdf`; ask if you cannot tell which one. A different PDF
   is refused by the CLI.
2. **Find what to fix.** Run both:
   - `kb l3 lint <doc-id> --pdf <pdf>` — layout problems, one per line as
     `§<section> <rule> line <n>: <evidence>` (rules R1–R8; exit 1 when
     there are issues).
   - `kb l3 report <doc-id>` — flagged sections with evidence.
   Fix only the sections these list. Leave every other section alone.
   Nothing listed → report that and stop.
3. **Read the unit.** The section's file is the `file:` of its row in
   `.kb/<doc-id>/_manifest.yaml`; its text is in
   `.kb/<doc-id>/<file>.raw.md`, from its `## ` heading to the next `## `
   heading. Read it; do not edit it. Compare with the PDF text where the
   evidence points.
4. **Write one draft per unit.** Save it as
   `.kb-work/<doc-id>/l3fix/<section-id>.md`, named by the section's current
   id. A draft holds the whole slice: it starts with the `## ` heading line
   and contains the unit's full content, changed or not.
   - **Merge or reorder** consecutive units of one chapter file: put
     `<!-- replaces: <id> <id> ... -->` as the first line, listing the
     current ids in file order, and write the result below it. Name the
     draft after the first id.
   - **Split** one unit: write several `## ` units in the same draft.
   - Units that are not consecutive, or sit in different files, need
     separate drafts.
5. **Apply.** Run
   `kb l3 fix apply <doc-id> --pdf <pdf> --assistant <name>` with `<name>`
   `claude-code`, `copilot` or `cursor` — the tool you are running in.
   To apply only some drafts, add `--section <id>` (repeatable). It prints
   one line per draft:
   - `§<name> applied → <new ids>` — done, the draft is deleted.
   - `§<name> unchanged` — the draft equalled L3; nothing to do.
   - `§<name> rejected: <check>: <detail>` — nothing was written and the
     draft stays.
6. **Handle each rejection.** Read the `<check>: <detail>`, correct the
   draft to satisfy it, run apply again with `--section <name>`. At most 2
   retries per section. Do not retry, and leave the section for the human,
   when the check is `status:` (the chapter file already has summarized or
   reviewed units), when it says to re-ingest, or when the only way to pass
   would be to add, reword or drop PDF text. When you give up on a section,
   delete its draft file under `.kb-work/<doc-id>/l3fix/` so a later apply
   does not pick it up again. Apply exits 1 when any draft was rejected,
   even if others were applied.
7. **Re-check.** Run `kb l3 lint <doc-id> --pdf <pdf>` again for the
   sections you applied.
8. **Report.** Give three lists: applied (with new ids), rejected (with
   the check and detail), left for the human. Then tell the user to run
   `kb l3 report <doc-id>` and check the changes themselves; you do not
   confirm. After they have confirmed, `kb summarize` fills the summaries
   (`kb ingest` leaves it to them while L3 fix is on).

## What a draft may change

Allowed:
- Section ids, headings and heading levels (`##` unit, `###`, `####` at
  most, no skipped level).
- Joining lines that the PDF broke into one paragraph.
- Removing a block that is an exact repeat of one that stays, and page
  header or footer lines (furniture) left in the text.
- List markup (`-`, `*`, `1.`, two levels), fenced code, and the inline
  marks `**`, `*`, `_` and `` ` ``.
- Replacing a garbled word with the word the PDF has at that place.

Forbidden:
- Adding, rewording, translating or "cleaning up" any text.
- Any change to a table.
- Touching `.kb/` files directly instead of writing a draft.

## Section ids

The word check treats a section id as text: a changed id must be text the
PDF shows. Take ids only from the PDF's own numbering (`4.2`, `4.2.1`,
`Điều 5`). Never invent an id.

A synthetic fallback id such as `x1` or a slug (`## x1 4.2 NGHỈ PHÉP NĂM`)
may only be deleted, leaving the PDF heading text (`## 4.2 NGHỈ PHÉP NĂM`).
A heading the PDF does not number keeps its text as written and gets no
number.

## Sections whose text layer is unusable

Use this only for a section that is scanned or has a broken font, so the
PDF text cannot be the reference (lint or the report shows `unverifiable`
or mostly mismatched content).

1. Render the pages:
   `kb l3 fix pages <doc-id> --pdf <pdf> --page <N> [--page <M> ...]`.
   It prints the PNG paths (`.kb-work/<doc-id>/pages/p<N>.png`). Open and
   read those images.
2. Write the draft from what the page images show, with the same rules as
   above. Still never change a table.
3. Apply that draft with `--from-image <id>` (the draft's first section id;
   repeatable): `kb l3 fix apply <doc-id> --pdf <pdf> --assistant <name> --section <id> --from-image <id>`.

`--from-image` skips the word check, so apply refuses it for a section
whose text layer is usable; then redo the draft without it, or leave the
section for the human. A change applied this way is marked unverified, and
the reviewer sees it must be checked against the PDF.

## Hard stops

- Switch off, document or PDF not found, or any CLI error you do not
  understand → show the output verbatim and stop. Do not guess options.
- Never use `--from-image` to get past a rejection of a section with a
  usable text layer.
- Never run `kb l3 confirm`, `kb l3 fix on` or `kb l3 fix off`.
