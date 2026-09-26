# Where knowledge lives

**The code and its tests are the primary documentation.** Markdown exists for what those two cannot express, and for nothing else.

That ordering is the whole file. Everything below is how to apply it while you are writing, rather than discovering it in review.

## Before you write a sentence of prose

One question, asked every time: **can the code or a test say this instead?**

Usually it can, and usually the answer is one of these:

| you were about to write | write this instead |
|---|---|
| what this function does | a name that says it |
| why this value | a named constant |
| how this is meant to behave | a test whose title is that sentence |
| what happens in the empty case | a test for the empty case |
| what this module contains | nothing. A reader can list the directory |

Prose is the fallback, not the default. A paragraph explaining behaviour is a test somebody did not write, and unlike the test it will still be there, still confident, long after the behaviour changed.

## What the two already say

**Code documents what the software does.** It is the only record that cannot drift, because it is the thing itself.

**Tests document how it is supposed to work.** That is the half code cannot carry: a promise, as opposed to a behaviour. The two overlap, and where they disagree one of them is a bug.

This is why a test title is a sentence. `rejects a second registration for the same credential id` is a line of documentation that runs. `test registration 2` is a number. Where a case is non-obvious, one comment saying why it matters earns its place, and the reaper leaves it alone.

## The gaps

Three things the pair genuinely cannot express. Prose is for these.

**Why a boundary sits where it does.** Code shows what calls what. Nothing in it points at the call that was deliberately not made, and a reader cannot see an absence.

**How to work here.** Process, not behaviour. What a contributor owes before they open a change.

**What this is.** For somebody who will use a thing and never open it.

## The map

Route by audience. Writing the right sentence in the wrong file is the second commonest failure here, after writing it at all.

| | audience | holds | does not hold |
|---|---|---|---|
| code and its tests | everyone | what is built, and what it promises | why a boundary is where it is |
| `ARCHITECTURE.md` | a developer | how the parts fit, and why the boundaries sit where they do | what any one part does |
| `CONTRIBUTING.md` | contributors, human and agent | how to work here: a bug fix comes with a test, a dependency is a last resort, the target before the feature | what the software does |
| `README.md` | whoever consumes this folder | what this is | how it works inside |
| `CLAUDE.md` | agents | what an agent has to do differently here | general craft, which belongs in `CONTRIBUTING.md` |
| `_todo/`, `_done/` | the owner | specs in flight | anything a committed file may name |

**A README's audience is the consumer of its folder, and that changes with the folder.** A README beside a user interface is for whoever uses that interface. A README in a shared package is for the developer importing it. Work out who opens that directory before you decide what the file says.

**`CLAUDE.md` is the smallest of these, and stays that way.** Most of what people put in it is craft that applies to anyone, and craft belongs in `CONTRIBUTING.md`. What stays is the part that is only true for an agent.

The repository states the current design and nothing else. The target repository's profile names which of these files exist here and what each one holds; where the two disagree, the profile wins, because it is about a real tree.

## While you write

1. **Reach for code or a test first.** Prose is what is left over.
2. **Route by audience, not by topic.** The question is who opens this file, never what the paragraph is about.
3. **Never create a new markdown file.** A new file is a change to this map, and the map is the owner's. Propose it.
4. **Nothing committed names `_todo/`, `_done/` or `_tmp/`.** They are gitignored, so a reference to them is a link to nothing on every machine but one.
5. **Present tense, current state.** No history, no changelog, no dated decision, no note about what this used to be. A record of what changed is a record that quietly stops being true.
6. **Third person.** Documentation describes the software, not the people around it. No *I*, *we* or *my*: a README opening "tooling I use" is a claim about a person, and it stops being true the day somebody else maintains it. No *you* or *your* either. Where the reader has to act, the imperative carries it with no subject at all. *Fill in the profile*, never *you fill in the profile*, and *type `/plan` to start a spec*, never *you type `/plan`*.
7. **One fact, one home.** The second copy is the bug, because the two drift and nobody is told which is wrong.
8. **Read `CONTRIBUTING.md` before you write code here.** It is where the obligations live, and it is written for you as much as for a person.
9. **Brief.** Every surviving sentence was chosen over a test. It should read like it.

Rule 6 governs documentation. An instruction addressed to whoever is writing is a different genre and stays in the second person: the agent files, the skill files, the voice files, and this one.

## The exception

Sometimes a fact outlives the work and has nowhere else to live: how an outside system behaves in a way nobody would guess, or a boundary no linter can hold.

Write it, in the file the map sends it to, in the present tense, as short as it can be said, and never as a story about what was decided. Then say you did, so somebody can disagree.

It is rare. Treat a second one in the same change as a sign you are writing prose to avoid writing a test.
