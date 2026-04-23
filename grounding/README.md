# Grounding Documents

Put your brand's grounding docs in this folder as Markdown files, then seed
them into the database:

```bash
python scripts/seed_grounding.py grounding/
```

The filename (without `.md`) becomes the document's key in the database.
The profile's `grounding_doc_keys` list controls which docs get injected
into classification and participation-guide prompts.

## Standard keys

The `example.yaml` profile expects these filenames (they map to
grounding_doc_keys):

- `competitive_positioning.md` — how your brand compares to competitors
- `voice_tone.md` — how your brand should sound on Reddit
- `icp_personas.md` — your ideal customer profiles
- `product_messaging.md` — approved product descriptions and claims
- `engagement_rules.md` — Reddit do's and don'ts for your team
- `content_strategy.md` — what kinds of threads to originate

You can add or rename keys — just make sure the profile's
`grounding_doc_keys` list matches the filenames you seed.

## Private grounding docs

For brand-specific (non-shareable) grounding docs, put them in
`private/grounding/` — that folder is gitignored. Then seed from there:

```bash
python scripts/seed_grounding.py private/grounding/
```
