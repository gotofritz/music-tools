---
name: deai
description: Rewrite text to remove tell-tale signs of LLM authorship. Accepts text inline or via a file path. Use when asked to "deai", "dehuman", "remove AI fingerprints", "make this sound human", or similar.
---

# deAI: Remove LLM Authorship Signals

Rewrite the supplied text so it reads as human-authored prose. The goal is to
preserve all factual content while eliminating patterns that fingerprint LLM output.

## Input

- **Inline**: text pasted after the slash command
- **File**: a path; read the file, rewrite it in place

## Process

Work through the checklist in order. Each pass is independent; run all of them.

---

### Pass 1 — Strip AI Vocabulary

Replace every overused AI word with a plain synonym or restructure the sentence.
Never swap one AI word for another.

| Banned word / phrase | Replace with |
|---|---|
| additionally (sentence-opener) | drop it; restructure sentence |
| align with | match, fit, suit |
| boasts (meaning "has") | has |
| bolstered | strengthened, supported |
| crucial | critical, key → or just drop |
| delve | examine, explore, look at |
| emphasizing / underscoring / highlighting (as superficial filler) | cut the phrase entirely |
| enduring | lasting, long-standing |
| enhance | improve, strengthen |
| fostering | building, encouraging |
| garner | get, win, earn |
| highlight (verb, filler) | show, reveal, demonstrate |
| interplay | interaction, relationship |
| intricate / intricacies | complex, detail, nuance |
| key (adjective, overused) | main, central, primary |
| landscape (abstract) | field, area, sector |
| meticulous / meticulously | careful, careful attention |
| pivotal | important, critical, decisive |
| robust | strong, solid |
| showcase | show, display, present |
| tapestry (abstract) | mix, blend, variety |
| testament | proof, sign, evidence |
| valuable | useful, important → or drop |
| vibrant | lively, active |
| stands as / serves as / marks / represents | is |
| refers to (in lead sentence treating a term as its own subject) | rewrite: "[Subject] is ..." |

---

### Pass 2 — Remove Superficial Analysis

Superficial analysis = a present-participle phrase tacked onto a factual sentence
that adds no sourced information, only implied significance.

**Pattern to cut:**
> [Fact], [verb]-ing [vague significance claim].

**Examples of what to cut** (keep the fact before the comma; delete the rest):
- ", marking a pivotal moment in the evolution of..."
- ", contributing to the socio-economic development of the region."
- ", reflecting its continued relevance in the..."
- ", highlighting their historical and pedagogical significance."
- ", underscoring the enduring practice of..."
- ", fostering a sense of connection and shared purpose."
- ", symbolizing its ongoing importance to..."

If the participle phrase carries a real fact, convert it to its own sentence with
a plain verb.

---

### Pass 3 — Remove Undue Significance / Legacy / Trend Language

Delete or rewrite sentences whose sole purpose is to announce importance rather
than convey information.

**Phrases that signal these sentences:**
- "marking a pivotal / key / significant moment"
- "represented a significant shift toward"
- "was part of a broader movement"
- "reflects broader trends in"
- "setting the stage for"
- "shaping the [landscape / trajectory / future] of"
- "key turning point"
- "evolving landscape"
- "indelible mark"
- "deeply rooted"

**Rule:** If a sentence could be deleted without losing any checkable fact, delete it.

---

### Pass 4 — Remove Promotional / Puffery Language

Neutral prose does not advertise. Replace or cut:

| Puffery | Neutral alternative |
|---|---|
| nestled in / nestled within | located in |
| in the heart of | in / at / near |
| breathtaking / stunning / picturesque | omit or describe specifically |
| vibrant community / rich cultural heritage | specific facts only |
| diverse array of | variety of → or list items directly |
| natural beauty | omit unless you can cite a specific feature |
| groundbreaking | first, novel → or drop |
| renowned | well-known, noted → or drop if not sourced |
| commitment to (vague) | cut; state what they actually did |
| diverse tapestry | variety, mix |
| rich history | specific historical facts instead |
| gateway to | entry point, main route → or just describe what it does |

---

### Pass 5 — Fix Copula Avoidance

LLMs avoid "is" / "are" / "has" and use marketing verbs instead. Revert:

| AI phrasing | Human phrasing |
|---|---|
| X serves as Y | X is Y |
| X stands as Y | X is Y |
| X acts as Y (when meaning "is") | X is Y |
| X features Y / X boasts Y | X has Y |
| X offers Y (when meaning "has") | X has Y |
| X maintains Y (when meaning "has") | X has Y |
| ventured into politics as a candidate | was a candidate |
| began his career as | was |

---

### Pass 6 — Fix Vague Attributions (Weasel Wording)

Every claim needs a specific source or a rewrite that removes the claim entirely.

**Patterns to fix:**
- "researchers and conservationists" → name them or cut
- "experts argue" → name the expert or cut
- "some critics argue" → name them or cut
- "industry reports" → cite the report or cut
- "observers have noted" → cut or attribute
- "modern researchers treat X as" → cite a researcher or rewrite as fact
- "several sources" when only one or two are cited → cut or match the count

If the claim is real but the source is vague, flag it: `[citation needed]`.

---

### Pass 7 — Remove Challenge / Future Prospects Formula

Delete or radically rewrite the canned "Despite X, faces Y challenges; future Z"
structure:

**Delete sentences matching:**
- "Despite its [positive word], [subject] faces several challenges..."
- "Despite these challenges, [subject] continues to..."
- "Future investments in / potential developments could..."
- Section headings: "Challenges and Future Directions", "Future Outlook",
  "Future Prospects", "Challenges and Legacy"

If real challenges exist and are sourced, state them plainly without the framing:
> "The canal faces silting in the northern reach." ✓  
> "Despite its success, the canal faces challenges including silting in the northern reach, which future technology could address." ✗

---

### Pass 8 — Fix Negative Parallelisms

Rewrite "not only X but Y", "not X but Y", "X rather than Y" constructions that
exist only for rhetorical effect.

- "not only dismissive but also unnecessarily harsh" → "dismissive and harsh"
- "isn't just sourcing — it's framing" → state the actual point directly
- "not a representation of self, but a mechanism for its constant reinvention"
  → pick the accurate description and state it once

---

### Pass 9 — Cut Structural Filler

- **Rule of three for its own sake**: "X, Y, and Z" where the list is padding, not
  exhaustive or meaningful. Reduce or rewrite as prose.
- **Section summaries**: Delete any paragraph or section that only restates what
  was just said ("In summary...", "In conclusion...", "Overall...").
- **Didactic disclaimers**: Delete "it's important to note", "it's worth noting",
  "it is crucial to remember", "it is important to consider", "may vary".
- **"Challenges" intro formulas**: see Pass 7.
- **Knowledge-cutoff hedges**: Delete "as of my last update", "based on available
  information", "while specific details are limited in available sources".

---

### Pass 10 — Simplify Sentence Structure

- Replace wordy copula-avoidance with the plain verb (see Pass 5).
- Prefer shorter sentences over compound sentences joined by em dashes (—).
- Replace stiff synonyms with common ones:
  - authored → wrote
  - relocated → moved
  - utilized → used
  - attempted → tried
  - passed away → died
  - commenced → began / started
  - approximately → about
  - in order to → to
  - as a result of → because of
  - the fact that → that / because
- Convert "there is a / there are" back where LLMs removed them.
- Restore "very", "perhaps", "tends to" where hedging is accurate.

---

## Output Rules

1. **Preserve all verifiable facts.** Never delete a fact; only delete unsourced
   significance claims.
2. **Preserve citations / references.** Move them if the sentence restructures,
   but never drop them.
3. **Do not introduce new content.** Only rewrite what exists.
4. **Do not improve style beyond the checklist.** This is not a general copyedit.
5. **For files:** overwrite the file in place. Report a summary of what changed.
6. **For inline text:** print the rewritten text, then a short diff-style summary
   of the changes (which passes fired, what was removed/replaced).

## What NOT to Change

- Accurate technical terms, even if they sound formal
- Direct quotations
- Proper names and titles
- Content that is already plain and specific
- Sentences whose only "AI sign" is perfect grammar
