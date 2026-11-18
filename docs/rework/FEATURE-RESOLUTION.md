# Feature resolution

Classified from the signed cards in `DECISIONS-LOG.md` on 2026-11-17. Nothing is cut. A defer stays working and unchanged. A simplify is a later slice, not a change made here.

| Id | Resolution | Why |
| --- | --- | --- |
| F01 Scan | keep | Core workflow |
| F02 Metadata lookup | keep | Core workflow. Rate limits stay (D07) |
| F03 Scoring, title cleanup, LVI, and oeuvre | keep | Do not retune |
| F04 Pinning | keep | D05 keeps the pinning doc |
| F05 Approve | keep | Normal approve pin behavior stays |
| F06 Skip and unskip | keep | |
| F07 Revert and unstage | keep | |
| F08 Conflicts | keep | Grouping stays. Pin writes are F37 |
| F09 Merges | keep | Grouping stays. Pin writes are F37 |
| F10 Partial stage | keep | |
| F11 Auto-stage | keep | D04 |
| F12 Hardlinks and the same-mount precondition | keep | Document the precondition. Do not switch to copies |
| F13 Library layout | keep | D03 |
| F14 Fingerprint identity | keep | |
| F15 Inode staged-or-not | keep | |
| F16 One scan and one auto-run | keep | D08 |
| F17 Session hydration | keep | |
| F18 Activity lock | keep | |
| F19 Credentialed providers | keep | D02 |
| F20 Keyless providers and contact email | keep | D02 |
| F21 While you were away | keep | D04. Later paging follows D07 |
| F22 Decision log | keep | |
| F23 Duration compare | keep | |
| F24 Health | keep | |
| F25 Bulk approve, unskip, and revert | keep | |
| F26 Library replace helper | keep | Path shape is F41 |
| F27 Unmerge API | defer | No static caller. D09 allows deleting it only after the parity list is green |
| F28 Fixture metadata backend | keep | Tests stay off the live network |
| F29 Schema migration and false-pin repair | keep | An old database must still open |
| F30 Static operator UI | defer | Workflows stay until the parity list is green (D01, D09). The old page is removed only in that UI slice |
| F31 Metadata API cache | keep | |
| F32 Scan cancel | keep | |
| F33 Discovery | keep | D06 adds a seam later. No ebook parser |
| F34 Manual hints and target preview | keep | |
| F35 Docker single service | keep | D01, D08. Defaults change under F47 |
| F36 README layout wording | simplify | Say both layouts from D03 |
| F37 Conflict and merge pin flags | simplify | D05. Match normal approve. Do not set every pin flag |
| F38 Unbounded list and conflict reads | simplify | D07. Page in SQL. UI must not render the whole library |
| F39 Provider registry versus `providers.py` | simplify | Split the live provider class. Lookup behavior stays |
| F40 `research` import guard | keep | The test stays. The package stays absent |
| F41 `replace_library_target` path shape | simplify | Delete the same series key the approve already computes |
| F42 MAM status versus lookup resolver | simplify | One resolver. D02 skip-when-unset stays |
| F43 `exclude.txt` helpers | defer | No caller and no test. Not marked cut |
| F44 `mam_exact` scoring prior | defer | Leave it. Do not retune scoring |
| F45 `library_cache` imports the holder | simplify | Break the core-to-app import under path B. Index reuse stays |
| F46 Activity-lock write outside `DB_LOCK` | simplify | Serialize that write with the shared connection |
| F47 Personal defaults in the public tree | simplify | Examples use `./data/seeds` and `./data/library` |
| F48 No authentication | keep | D08 |
