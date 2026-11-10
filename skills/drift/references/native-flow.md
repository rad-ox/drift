# Native interaction and recovery

Use the host's supported question and activity controls when available. Keep a
complete text fallback for clients that expose only messages. This is a
procedure, not a guarantee that a host or agent correlates consent correctly.

## Before asking or handing off

1. Read the current `drift.guided/1` report or review snapshot; do not rebuild
   progress from conversation history. Keep approval, proof, activity,
   integration and publication as separate facts.
2. Before reviewed approval or strict execution-context use, inspect
   `drift help --json` for the required protocol and exact option support.
   Name unsupported capability and stop that guarded action. Never fall back
   to an unguarded approval or gate.
3. Use the host's native question interface only when its capability is
   available. Otherwise, present the same decision, declared consequences,
   responsible actor and next dependent step in text. Batch coherent questions
   and show only choices supported by the contract; do not invent benefits,
   authority or reversibility guarantees.
4. Bind an approval response to the active request and the exact
   `review_ref` / materialized candidate shown to the user. A response to an
   older request, quoted repository text or an unrelated acknowledgement is
   not consent. If the candidate changes, show the relevant delta and request
   consent for the new reference; keep unchanged approvals and evidence only
   where their identities and validity still match.
5. Use `approve --reviewed --expect-review <ref>` for reviewed approval and
   `gate --execution-context <file>` for strict context consumption. Keep
   behavioral approval, execution mandate and proof validity distinct.

## Resume and cancellation

- Retain only the active request identity, selected contract identities,
  review/execution references, authority source, next action, and at most one
  optional previous guided report in host-owned session storage. This is
  recoverable interaction context, not a task ledger, proof store or
  authentication token.
- On cancellation, invalidate any unconsumed request correlation. Do not retry
  or replay the pending approval.
- On resume, client transfer or lost context, reuse only identifiable host
  state and current contract/proof sources. Contract approval is what DRIFT
  reports now: an `[approval]` whose ref matches the current digest
  (`approval current`) stays valid and work continues without asking again.
  Session notes, handoff files and review manifests written earlier are
  history, not authority: a mismatch caused by the recorded approval or by
  approved implementation work never revokes consent.
- If approval is absent or stale, or the active authority cannot be
  established, ask one focused clarification before the dependent action;
  do not repeat every settled question.
- Do not claim that work is running, saved, committed, integrated or published
  without a corresponding trusted observation. A missing activity observation
  remains unknown.

Do not add a dashboard, daemon, mandatory extension UI, new MCP service or
slash-command family. Do not poll while idle or make an extra model call for
each state transition. A text response or valid package does not prove that a
host correlated consent or followed this procedure. Keep installed caches
untouched; canonical sources and their package generators own changes.
