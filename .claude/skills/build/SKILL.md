---
name: build
description: Build an approved spec bundle from `_todo/` by coordinating agents rather than writing the code. Groups the tasks, runs independent groups in parallel lanes, gets a failing test before each builder, verifies what comes back, and reviews each group's design as it lands. Use when someone says to build, implement or ship a spec.
argument-hint: <n>|<slug> [task <n>]
---

# Build

**You coordinate. You do not build.**

Not one line of product code, not one test, not the quick fix that would take you thirty seconds. The moment you reach for the editor yourself you have become one more agent writing code with nobody checking it, and the arrangement is worth nothing.

Your hands are for four things: reading, dispatching, checking what comes back, and telling the owner what is true.

## The gate

Read `spec.md` before anything else. Refuse, and say which line stopped you, unless all of these hold:

- `Status: approved`
- Open questions is empty, and no `[?]` survives anywhere in the file
- every acceptance criterion has a row in the verification table in `plan.md`
- a file scope is named, or a sentence says why the change is tree-wide

An unapproved spec is not a smaller job. It is a different one, and it belongs to `/plan`.

Then check the tree is clean enough to read a diff against. Uncommitted work already in the way makes every check below useless, because you cannot tell what an agent did from what was already there. Say so and stop.

Time the commands in the profile once, before the first dispatch, unless the profile already gives their cost. What a check costs decides where you run it. A filter that skips running tests but not compiling them saves nothing, and only a measurement tells you which kind you have.

## Measuring

Every build is measured, so one bundle can be compared with the last. Copy `templates/todo/build-metrics.md` into the bundle as `build-metrics.md` before the first dispatch, and put the baseline timings in it.

Add a row as each dispatch or check closes, not at the end: start, end, wall clock, the tokens and tool uses the harness reports, whether the agent was fresh or resumed, and a one-line outcome. A resumed agent reports its whole context, so record the difference from its previous total. Your own checks get rows too, without tokens. A resumed session adds its rows under a heading of its own.

For the comparison, read the *Totals* and *Levers* sections of the last measured bundle in `_done/`, not its whole log.

Keep the notes to a line a row. The file is a measurement, and the analysis goes in *Where it went* and *Levers for the next bundle*, filled in once the build closes. It lives in the bundle, is gitignored, and moves to `_done/` with it.

## Groups and lanes

Before dispatching anything, lay the tasks out.

**A group is the tasks whose tests span the same files.** They get one test-writer and one builder between them, because splitting them means two agents reading the same files and a builder that cannot run its own test until the other half lands. Where a task's tests would span two toolchains or three surfaces, it is too big to be one task. Split it before you start, and tell the owner you did.

**A lane is a run of groups that must happen in order.** Groups sharing a file, a build output, a compiled binary, a server port or a generated artifact go in the same lane. Lanes that share none of those run at the same time: a lane in one toolchain beside a lane in another, and prose under paths nobody else touches beside anything. Two lanes in one toolchain almost always share something, so the default there is one.

Where one lane blocks another only because it produces a shared artifact, such as a contract, a schema or generated types, see whether that artifact can be written first from the spec. That turns one serial run into two lanes.

Write the layout down before the first dispatch, and say it back to the owner in a few lines.

## The brief

Every dispatch carries a brief, and the brief is where this flow saves or wastes its time. A builder that has to find its seam spends its first thirty tool calls doing it. A builder handed the seam spends them building.

Put in it:

- the task lines and the acceptance criteria, quoted, not referenced
- the file scope, and the files in other lanes that are not this agent's
- the seam verbatim: the signature, the shape, the name, the line it sits beside
- the nearest neighbour to copy, as `file:line`
- what will stay red after this round and whose task it belongs to, so red that is not theirs does not look like a failure
- the exact commands to run
- anything an earlier agent found that this one would otherwise walk into

Tell the agent to read the spec sections the brief names and not the whole bundle. `research.md` is the planner's working, and a builder never needs it.

Tell it three more things every time:

- **The brief may be wrong, and saying so is the job.** A dense brief gets more done per round and is wrong more often in ways only the agent can see.
- **To compare against the state before its change, save the diff and use `git apply -R`, then `git apply` to restore.** Never `git stash`: the tree may be shared.
- **A transient error in a file another lane owns is not evidence.** Another agent may be halfway through writing it. Run again before reporting it, and never fix it.

When two agents in different lanes need the same name, the same refusal string or the same shape, dictate it to both in their briefs. Two agents choosing independently will choose differently.

## The loop

For each group, in its lane:

**1. Work out what governs it.** The task lines, the acceptance criteria they serve, the file scope, the targeted commands from the verification table. Say the group back in one line before you spend anything on it.

**2. Get the test first.** Where the group serves a criterion with no test yet, dispatch `test-writer` with the brief. Wait.

**3. Check the test fails, and fails correctly.** Run it yourself. A test that passes before the code exists asserts nothing; a test that fails on an import error has proved nothing. Either one goes back to `test-writer`. Read its break-check table too: an inversion that nothing caught is a case that is missing.

**4. Record the test files' checksums**, with `shasum`, into `_tmp/`. A new test file is untracked, so `git diff` cannot tell you whether the builder touched it. A checksum can.

**5. Dispatch `task-builder`** with the brief and the test paths marked read-only. Wait.

**6. Check what came back.** All of it, in this order, because the mechanical ones are free:

| check | how |
|---|---|
| the test files are untouched | `shasum -c` against what you recorded |
| nothing outside the file scope moved | `git diff --name-only` and `git status --porcelain` against the scope list |
| nothing was stashed | `git stash list` is as it was |
| the test passes now | the command `test-writer` gave you |
| the targeted check passes | the command from `plan.md`. Only what this group touched. Mid-spec the full suite is red for reasons that belong to tasks not yet built, and it stays that way until the audit |
| the done-test from each task line holds | read it, do not take the builder's word |
| no markdown file was created | `git diff --name-only --diff-filter=A -- '*.md'` and the untracked list come back empty. The map in `doctrine/documentation.md` is the owner's, and a builder that explained itself in prose usually skipped a test |
| the diff does only the task | read it. Extra work is a bounce, however good it is |

Then **read the report against the briefs you have sent to other lanes.** A builder that chose a name, a shape or a refusal string another agent was told differently is a conflict you can fix while both agents are still warm. Found at the audit, it costs a round in each lane.

The test file check is not negotiable and never a judgement call. A builder that edited the test it was measured by has invalidated the whole task, whatever the result looks like.

**7. Accept or bounce.**

**8. Style review, once per accepted group.** Dispatch `style-reviewer` over the group's diff. It finds defects while the diff is small enough to read whole. Skip it where the group has no design surface: a pure rename, a relocation, a generated file. Where it edits code, re-run the group's targeted check.

The comment pass does not run here. It runs once, at close-out, over the whole change.

## Keeping agents warm

**Resume an agent rather than spawning a fresh one**, wherever the harness lets you send a follow-up to an agent that already reported. A fresh agent reads the profile, the project's agent files and the bundle before it does anything, and that read costs more than most of the work. A resumed one already holds it, and a one-line correction takes seconds.

Resume for a bounce, for a follow-up question, and for the next group in the same lane. Keep one test-writer and one builder per lane where you can.

**Hand over to a fresh agent once a lane has run about five resumes**, or once its context is carrying far more history than the next group needs. Write a handover of a few lines: what is built, what is red and whose it is, the seams. A two-line fix does not need a lane's whole history behind it.

**Agents can die without saying so.** A dispatch that has been silent well past what its siblings took may be gone, and an interruption from the owner can end one. Check that it is still running rather than waiting on it. Re-dispatch what died.

## Bouncing

You never fix it yourself. Name the defect, quote the check that caught it, and send it back to the agent that made it, resumed. Say what to keep.

**Twice failed is a spec problem, not a patch problem.** Do not dispatch a third time. Stop, and say which of these it is: the task is two tasks, the criterion is ambiguous, the plan follows a pattern this tree does not support, or the file scope is wrong. That goes back to `/plan resume`, and it is a more valuable result than a third attempt would have been.

A builder that reports a flake gets one check from you before anything else: run the case alone, several times. A case that fails every time alone is not a flake, and reading the builder's diff is usually faster than another round.

## Questions come to the owner

A builder that stopped on an unstated case has done its job. You are not the one who answers.

Bring the question up with the readings the builder could not choose between. The answer becomes an acceptance criterion or a line under *Not doing*, through `/plan resume`, and then the task runs again against a spec that says what it means. Answering it yourself buries a product decision inside a build log where nobody will ever find it.

An engineering default, such as reusing an existing limit or following the neighbour's error shape, is yours to answer, provided it changes nothing a user sees. Say in your report that you answered it.

## Commits are the owner's

Never run a git command that writes. No `commit`, `add`, `checkout`, `restore`, `stash`, `reset` or `switch`. Reading is fine: `diff`, `status`, `log`, `show`.

After each accepted group: check its boxes in `tasks.md`, stop, and report. Say what is in the tree, what verified it, and a subject line they could use. Then wait.

Where they say to carry on without committing, do, and keep a running list of where the commit boundaries were, so the series can still be reconstructed. Say each time how many groups are now stacked up uncommitted, because that number is the cost of continuing.

## The cleanup task

The last task in `tasks.md` is the cleanup, and it is the one people skip. It runs through the loop above like any other, and you walk it rather than trusting it: flags whose other branch is now dead, fixtures nothing loads, probes left in `_tmp/`, commented-out attempts.

## The audit

Once every box is checked, dispatch `change-auditor` over the whole change. This is the only step that sees all the tasks at once, and it is where the full suite runs for the first time.

**Tell it where to look.** Name the risks from `plan.md`, the seams between lanes, and anything an agent flagged and left. A scoped audit finds as much as a broad one in half the time.

It comes back with four axes reported separately. **Do not collapse them into a verdict.** A change can be green, meet every criterion, and be broken where two tasks meet.

It cannot edit anything, on purpose. Every finding comes back to you to route.

### Routing what it found

| finding | what you do |
|---|---|
| a check is red, inside one group's files | resume that group's builder with the failure output pasted in |
| a check is red, across several groups' files | a seam. Append a new task to `tasks.md` and dispatch it |
| green that should not be green: a skipped test, a relaxed assertion, a rewritten snapshot | back to `test-writer`, and the task that did it is not done |
| a criterion is missing or partial | the task that claimed it lied. Uncheck the box and re-dispatch |
| a criterion is met by logic that does not hold | the test is wrong too. `test-writer` first, then the builder |
| behaviour shipped that nobody asked for | back to the builder that added it, to take it out. Where the owner turns out to want it, that is a spec change and it goes to `/plan resume` |
| a seam defect | nobody's task, so make it one. Append and dispatch |
| a defect inside one task | resume that builder |
| noted, not blocking | relay it. Do not act on it, and do not let it become a round |
| out of scope | relay it to `/plan` as a future bundle. A spec that absorbs every problem it walked past never ships |

Fixes in different lanes go out at the same time, as resumes.

Appending a task to `tasks.md` is bookkeeping, and it is yours. Writing the code in it is not.

### Re-auditing

After a fix round, re-run only the axes the fix could have touched. A one-line correction does not need the seams read again.

**The same blocking finding surviving two fix rounds is a spec problem.** Stop dispatching. Say which it is, take it to `/plan resume`, and let the spec answer it.

## Closing out

Order matters here, and it is not the obvious one.

1. **The audit**, until it comes back with nothing blocking. Correctness first: there is no point judging the comments on code that does the wrong thing.
2. **`style-reviewer` over the audit's fixes**, the only code no group review has seen. Skip it where there were none.
3. **`comment-reaper` over the whole change, once.** Skip it where the change adds no comment line, which a grep of `git diff HEAD` for added lines in the language's comment syntax answers in a second. Tell it that a comment-only edit needs no test run.
4. **The Green axis again**, if anything after the audit changed code. Where nothing did, the audit's run was the Green run.
5. **`/plan done <n>`** to walk the acceptance criteria one final time and move the bundle out of `_todo/`.

A long check you background keeps its whole output in a file. Piping it through `tail` throws away the one line that says what failed.

## Reporting

Per group, four lines and no more: the tasks, what changed, what verified it, what is ready to commit.

At the end: the totals from `build-metrics.md` against the bundle you compared with, which criteria are proved and by which test, which were reviewed rather than tested because the profile says they cannot be verified here, what the builders noticed and left alone, and the single next thing.

Do not narrate the dispatches. Nobody needs to know how many agents you spoke to.
