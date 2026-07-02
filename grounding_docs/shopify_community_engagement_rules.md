# Shopify Community Engagement Rules: Onramp Funds

Shopify Community (community.shopify.com) runs on Discourse and is
operated directly by Shopify, not a third party. Its rules are stricter
and more explicit than Reddit's subreddit-by-subreddit norms, and they
are enforced by Shopify's own moderation team, not volunteer mods. Read
this whole document before generating any participation guidance for a
Shopify Community thread. Where it conflicts with `reddit_engagement_rules`,
this document wins for Shopify Community threads.

Facts below were verified directly against community.shopify.com's public
FAQ/guidelines page and `categories.json` on 2026-07-02. Anything not
directly confirmed is marked [VERIFY].

## The Hard Constraint: Self-Promotion Is Board-Restricted

Shopify's own guidelines state that unsolicited/self-promotional mentions
of products, services, websites, or blogs are **prohibited outside the
"Ask & Offer" board** (slug: `ask-offer`, category id 294). This is not a
soft norm like Reddit's "self-promotion gets flagged" — it's the platform's
stated moderation policy.

**Consequence for Onramp:** Recommending Onramp by name, linking
onrampfunds.com, or describing Onramp's product as a solution is only
appropriate:
1. Inside the Ask & Offer board, or
2. As a direct, contextual answer to someone explicitly asking for a
   financing recommendation elsewhere — and even then, Shopify's guidelines
   require you to "explain clearly and contextually why it's appropriate
   for the question, and be transparent about any fees." A drive-by mention
   is not enough; the recommendation has to be genuinely responsive to
   what was asked, not appended to an unrelated answer.

Outside those two cases: contribute the operational knowledge (how
payout gaps work, what to check in a financing offer) without naming
Onramp. This mirrors the "no disclosure needed" tier from
`voice_tone` — share expertise, don't attach a brand to it.

## Operating Decision: No Links, Ever

Confirmed 2026-07-02: Onramp does not need to post links on Shopify
Community. This is now a hard rule, not a situational judgment call.
**Never include a URL in a Shopify Community reply** — no
onrampfunds.com, no onrampfunds.com/compare, nothing. `suggested_links`
in a participation guide for a Shopify Community thread should always be
empty.

What this removes:
- The new-account link-rate-limiting risk (Discourse commonly throttles
  how many links a low-trust account can post) — moot with zero links.
- Shopify's "external linking discouraged as a general practice" norm —
  also moot.

**What this does not remove:** the Ask & Offer board restriction above is
about naming/describing Onramp as a product or service, not specifically
about URLs. A link-free reply that still pitches Onramp's pricing and
features outside Ask & Offer is just as much a guideline violation as one
with a link. Going link-free simplifies the voice (pure expertise-sharing,
a spoken disclosure when warranted, never a pitch) — it does not create a
loophole to describe the product outside the sanctioned venue.

## Hard "Do Nots" (Shopify Community-Specific)

1. **Do not post contact details or ask someone to DM you, in a reply.**
   Shopify's guidelines are explicit: if you want to be reachable, put it
   in your community profile bio, not in a reply. This is stricter than
   Reddit's voice-tone preference against "happy to DM" endings — here
   it's a platform rule, and pushing it may get the reply removed.
2. **Do not post templated or copy-pasted replies across multiple topics.**
   Shopify's guidelines call this out by name as forbidden. Every reply
   must be written for the specific thread.
3. **Do not post links at all.** See "Operating Decision: No Links, Ever"
   above — this supersedes the usual "a link may supplement an answer
   that stands on its own" guidance from `reddit_engagement_rules`. On
   Shopify Community specifically, the answer must always stand on its
   own with zero links.
4. **Do not sock-puppet, astroturf, or fake being a customer.** Same rules
   as Reddit (`reddit_engagement_rules`) apply here without modification.
5. **Do not attack competitors directly.** Same as Reddit — describe
   tradeoffs, don't disparage a named competitor.
6. **Do not engage in threads referencing Onramp's Trustpilot reviews,
   UCC liens, or legal/collections matters.** Same escalation rule as
   Reddit. Flag to [VERIFY: internal escalation contact — same as Reddit's,
   or a different owner for Shopify's official-channel visibility?] and do
   not respond.

## When to Engage

### Reply to an existing thread
- Someone in Payments + Shipping & Fulfilment, Accounting & Taxes, or
  Start a Business is describing a cash flow problem Onramp actually solves
  (payout timing, inventory restock, PPC scaling) — answer without naming
  Onramp unless they've asked for a recommendation directly.
- Someone explicitly asks for financing recommendations or names Shopify
  Capital and asks about alternatives — this clears the bar for naming
  Onramp, with fee transparency and clear relevance per the hard constraint
  above.
- Someone has factually incorrect information about how revenue-based
  financing or Shopify Capital eligibility works.

### Post in the Ask & Offer board
- This is the sanctioned venue for describing Onramp as a product. Treat
  it the way `reddit_engagement_rules` treats thread origination: transparent
  company association, no fake-customer framing, disclosure up front.

### Skip
- The thread is a Shopify support ticket in disguise (account access,
  billing disputes, technical bugs) — not a financing conversation, and
  Shopify staff (identifiable by "Social Care Team" / staff badges in
  replies) are already handling it.
- The seller's business is clearly outside Onramp's eligibility (non-U.S.,
  pre-revenue, not meeting the $3K/month minimum from `icp_personas`).
- The question is purely technical (checkout configuration, app setup)
  with no financing angle.

## Disclosure Norms

Same tiers as `voice_tone` and `reddit_engagement_rules`, with one addition:
Shopify's own guidelines require fee transparency any time a product or
service is offered as a solution, independent of Onramp's own disclosure
policy. Both requirements apply together — disclose affiliation AND state
that a fee applies, in the same short passage. Do not separate them into
"disclose who I am" now and "explain the fee" three replies later.

## Voice Calibration

Shopify Community skews toward operators who are less Reddit-native than
`voice_tone`'s target register assumes — many users are asking Shopify
support-style questions, not swapping war stories. Keep the same hard
gate (`voice_tone` STOP block: word count, no em-dashes, no bold, no
forbidden phrases) but expect replies to run more instructional and less
peer-banter than a Reddit comment. Match the register of an experienced
seller helping in a support forum, not a Reddit thread.

## Operational Notes

- **New-account link-posting limits: moot.** Discourse forums commonly
  rate-limit how many links a new/low-trust account can post, but the
  no-links-ever decision above means this never comes into play. Trust
  level still matters for other things (how fast a new account can post
  at all, reply frequency limits) — worth confirming [VERIFY] before
  high-volume participation, just not for link-related reasons.
- **Staff replies:** Shopify staff (Social Care Team) frequently answer
  technical questions directly in these boards. Do not compete with or
  contradict an existing staff answer on a technical point; if a staff
  reply already resolved the technical question, only add value on the
  financing angle they didn't cover.
- **No keyword search discovery:** Unlike Reddit, this MCP cannot search
  Shopify Community by keyword (robots.txt disallows `/search`). New
  threads are found via category browsing (`shopify_ingest`) or by feeding
  in specific URLs found through external search (`shopify_ingest_urls`) —
  see `shopify_scraper.py` docstring for why.

## Escalation Protocol

Same four levels as `reddit_engagement_rules`. One addition: because
Shopify itself moderates this forum and staff are visibly present, a
Level 2+ situation here is more likely to surface to Shopify's own team
before Onramp's. Escalate internally at the same threshold, but do not
assume Onramp controls the pace of resolution the way it might on Reddit.
