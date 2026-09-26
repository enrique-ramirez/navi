---
name: plan
description: Turn an idea into a spec bundle under `_todo/` that another agent can build from, then approve it and close it out. Use when someone describes work to be done rather than asking for it to be done, or says to spec, plan or scope something.
argument-hint: [<brief>] | resume <n> | approve <n> | done <n>
---

# Plan

`spec-planner` does the work. This decides which of four jobs it is doing, and handles the two that are bookkeeping rather than judgement.

## Work out the job

| argument | job |
|---|---|
| a brief, or nothing | a new bundle. With nothing, ask for one sentence about the problem and stop there |
| `resume <n>` or a slug | pick up an open bundle and carry on the interrogation |
| `approve <n>` | record the owner's approval |
| `done <n>` | cleanup and move to `_done/` |

Say the job and the bundle back before you start, so a wrong reading costs one line.

## A new bundle

Check `_todo/INDEX.md` first. A brief that matches an open row is a `resume`, not a new number, and two bundles for one piece of work is the commonest way this goes wrong.

Launch `spec-planner` with the brief verbatim, plus any constraint the caller mentioned in passing. Wait for it.

Relay its assumptions and its questions. Do not answer the questions on the owner's behalf, and do not soften the ones that sound like product decisions: those are the ones worth their turn.

Feed the answers back to the same agent. Two rounds is normal. Where a third round is still moving the acceptance criteria, say that the idea is not settled and offer to split it.

## Resume

Read the bundle before launching anything, and lead with where it stands: which open questions survive, and which acceptance criteria have no test in `plan.md` yet. Then launch `spec-planner` pointed at it.

A bundle whose spec has not moved in weeks is usually dead. Ask whether to close it before spending a round on it.

## Approve

Approval is the owner's, and yours is the checking.

Refuse and say why when any of these holds:

- Open questions is not empty, or a `[?]` survives anywhere in `spec.md`
- an acceptance criterion has no row in the plan's verification table
- Not doing is empty
- no file scope, and no sentence saying why the change is tree-wide

Otherwise set `Status: approved` and write the Approved line as a fact: what was agreed, against which draft, and the date. Never the words they typed. "go ahead" records nothing, and it reads as nothing a year later.

## Done

The last task in `tasks.md` is the cleanup, and it is the one people skip.

Walk it before moving anything. Flags whose other branch is now dead, fixtures nothing loads, probes left in `_tmp/`, commented-out code. Check the acceptance criteria against what actually shipped, and where one drifted, say which side is wrong rather than editing the spec to match.

Then run `/review` over the change if it has not been run, `git mv` nothing, and move the bundle with a plain `mv` to `_done/NNN-slug/`. Drop its row from `_todo/INDEX.md`.

Nothing is archived into the repository. Where the work turned up a fact that outlives it, a way some outside system behaves that nobody would guess, propose one short present-tense line in the file the profile's documentation map names, and let the owner accept it.

## Building from a bundle

Whoever builds reads `spec.md` and `tasks.md`, takes the first unchecked task, does that one, and stops. Not the next one, and nothing outside the file scope.

An unstated case met mid-task is a question, never a decision. Bring it back here and it becomes an acceptance criterion or a line under Not doing.
