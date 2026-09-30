import { useQuery } from "@tanstack/react-query";
import { getDefaultNormalizer } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
	AcceptDecision,
	AlbumState,
	AlbumView,
	Decision,
	PlanEntry,
} from "@/shared/api/types";
import { fakeFetch } from "@/test/fakeFetch";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import decisionHold from "@/test/fixtures/decision-hold/plan.json";
import soundtrackChoice from "@/test/fixtures/soundtrack-choice/plan.json";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { AlbumActions } from "./AlbumActions";
import { usePending } from "./pending";

const DROP = "20260929-210000";
const N = "01";
const ALBUM = `/api/drops/${DROP}/albums/${N}`;

const NOT_ACCEPTED = "the preview has not been accepted yet";
const COLLISION = "C/Bare Band/(2011) Bare Album is planned by album 02 too";
const HELD = `held: collision: ${COLLISION}`;
// What the server sends in `reason` and `rule`. The page speaks from the codes
// through the catalogue, so this text must never reach the screen.
const SERVER_TEXT = "SERVER TEXT";
const REFUSED = "'1-1': 'XYZZ' is not a frame of this file's format";
const LIBRARY_PATH = "/srv/music/library/C/Clean Band/(2010) Clean Album";

// Each case clones, so no case edits a fixture another case reads.
function entry(plan: { albums: unknown[] }): PlanEntry {
	return structuredClone(plan.albums[0]) as PlanEntry;
}

function view(preview: PlanEntry, over: Partial<AlbumView> = {}): AlbumView {
	return {
		drop: DROP,
		n: N,
		name: "Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview,
		files: [],
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: preview.destination
			? `/srv/music/library/${preview.destination}`
			: null,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		duplicate: null,
		approvable: {
			ok: false,
			reason: SERVER_TEXT,
			code: "not-accepted",
			hold: null,
		},
		...over,
	};
}

function accept(
	preview: PlanEntry,
	over: Partial<AcceptDecision> = {},
): Decision {
	return {
		action: "accept",
		release_id: preview.release_id!,
		edits: {},
		game: null,
		cover: null,
		...over,
	};
}

/** auto-clean as identify first leaves it: no decision yet. */
function freshClean(): AlbumView {
	return view(entry(autoClean));
}

/** auto-clean once agitha wrote an accept: no holds, so Approve is on offer. */
function acceptedClean(over: Partial<AlbumView> = {}): AlbumView {
	const preview = entry(autoClean);
	preview.decision = "accept";
	return view(preview, {
		decision: accept(preview),
		approvable: { ok: true, reason: null, code: null, hold: null },
		...over,
	});
}

/** soundtrack-choice as identify first leaves it: the choice on offer, none made. */
function freshScore(): AlbumView {
	return view(entry(soundtrackChoice));
}

/** soundtrack-choice once `soundtrack` was chosen and accepted. */
function acceptedScore(): AlbumView {
	const preview = entry(soundtrackChoice);
	preview.decision = "accept";
	preview.game = "soundtrack";
	preview.holds = [];
	preview.state = "auto";
	return view(preview, {
		decision: accept(preview, { game: "soundtrack" }),
		approvable: { ok: true, reason: null, code: null, hold: null },
	});
}

/** decision-hold: an accept agitha wrote, still held by a `decision` hold. */
function heldView(): AlbumView {
	const preview = entry(decisionHold);
	const hold = { kind: "collision" as const, detail: COLLISION };
	preview.holds = [...preview.holds, hold];
	return view(preview, {
		decision: accept(preview),
		approvable: { ok: false, reason: SERVER_TEXT, code: "held", hold },
	});
}

// No control name and no text on screen carries the server's sentence.
function expectNoServerText(region: HTMLElement) {
	expect(region).not.toHaveTextContent(SERVER_TEXT);
	for (const button of within(region).getAllByRole("button"))
		expect(button).not.toHaveAccessibleName(new RegExp(SERVER_TEXT));
}

// What `GET .../albums/01` answers now; a case moves it on as the server would.
let served: AlbumView;

function json(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "content-type": "application/json" },
	});
}

let net: ReturnType<typeof fakeFetch> | undefined;

type Handlers = Record<string, (req: Request) => Response | Promise<Response>>;

function serve(initial: AlbumView, handlers: Handlers = {}) {
	served = initial;
	net = fakeFetch({ [`GET ${ALBUM}`]: () => json(served), ...handlers });
	return net;
}

afterEach(() => {
	net?.restore();
	net = undefined;
});

// The server's answer to a decision: queued for identify, which has started.
function identifying(): Response {
	served = { ...served, state: "identifying", busy: true };
	return json({}, 202);
}

function posts(path: string) {
	return (net?.calls ?? []).filter(
		(call) =>
			call.method === "POST" &&
			new URL(call.url).pathname === `${ALBUM}${path}`,
	);
}

const RUNNING: AlbumState[] = ["queued", "identifying", "applying"];

// The last pending the harness saw, so a case can compare the POST body with the draft.
let latest: ReturnType<typeof usePending> | undefined;

function Actions({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	const title = view.preview?.files[0]?.after.TALB?.[0] ?? "";
	return (
		<>
			<h1>{title}</h1>
			<AlbumActions view={view} pending={pending} />
		</>
	);
}

// Polls every 20 ms rather than the page's 2 s, so the cases wait on real
// timers with bounded `findBy` and no fake clock. The 2 s interval is the
// album page's to test, not this component's.
function Harness() {
	const { data } = useQuery<AlbumView>({
		queryKey: ["album", DROP, N],
		queryFn: async () => (await fetch(ALBUM)).json(),
		refetchInterval: (query) =>
			query.state.data && RUNNING.includes(query.state.data.state) ? 20 : false,
	});
	return data ? <Actions view={data} /> : null;
}

async function show(initial: AlbumView, handlers: Handlers = {}) {
	serve(initial, handlers);
	const user = userEvent.setup();
	renderWithProviders(<Harness />);
	const region = await screen.findByRole("region", { name: "Actions" });
	return { user, region };
}

const WAIT = { timeout: 2000 };

// The status region once it says `text`. A status that already shows something
// else must not satisfy the wait.
async function statusSaying(text: RegExp): Promise<HTMLElement> {
	const found = await screen.findByText(
		text,
		{ selector: "[role='status'], [role='status'] *" },
		WAIT,
	);
	return found.closest("[role='status']") as HTMLElement;
}

function approve(region: HTMLElement) {
	return within(region).getByRole("button", { name: /^Approve/ });
}

describe("AlbumActions", () => {
	describe("the soundtrack choice (criterion 27)", () => {
		it("offers video game music, soundtrack and neither when the preview offers the choice", async () => {
			const { region } = await show(freshScore());

			const group = within(region).getByRole("radiogroup", {
				name: "Soundtrack",
			});
			expect(within(group).getAllByRole("radio")).toHaveLength(3);
			for (const name of ["video game music", "soundtrack", "neither"]) {
				expect(within(group).getByRole("radio", { name })).not.toBeChecked();
			}
		});

		it("checks the choice the last decision made", async () => {
			const { region } = await show(acceptedScore());

			const group = within(region).getByRole("radiogroup", {
				name: "Soundtrack",
			});
			expect(
				within(group).getByRole("radio", { name: "soundtrack" }),
			).toBeChecked();
			expect(
				within(group).getByRole("radio", { name: "neither" }),
			).not.toBeChecked();
		});

		it("offers no soundtrack choice when the preview does not", async () => {
			const { region } = await show(freshClean());

			expect(within(region).queryByRole("radiogroup")).not.toBeInTheDocument();
			expect(within(region).queryAllByRole("radio")).toHaveLength(0);
		});

		it("sends the chosen answer as the decision's game", async () => {
			const { user, region } = await show(freshScore(), {
				[`POST ${ALBUM}/decision`]: identifying,
			});

			await user.click(within(region).getByRole("radio", { name: "neither" }));
			await user.click(
				within(region).getByRole("button", { name: "Update preview" }),
			);

			await statusSaying(/identifying/);
			expect(posts("/decision")).toHaveLength(1);
			expect(JSON.parse(posts("/decision")[0].body)).toMatchObject({
				action: "accept",
				release_id: freshScore().preview!.release_id,
				game: "neither",
			});
		});
	});

	describe("Update preview (criterion 28)", () => {
		it("posts the draft, shows identifying, then the new preview with the draft settled", async () => {
			const fresh = freshScore();
			let sent: Decision | undefined;
			const { user, region } = await show(fresh, {
				[`POST ${ALBUM}/decision`]: async (req) => {
					sent = (await req.json()) as Decision;
					served = { ...served, state: "identifying", busy: true };
					return json({}, 202);
				},
			});

			await user.click(
				within(region).getByRole("radio", { name: "video game music" }),
			);
			const draft = structuredClone(latest!.draft);
			await user.click(
				within(region).getByRole("button", { name: "Update preview" }),
			);

			// The body is the draft: the chosen candidate and the choice, nothing else.
			expect(posts("/decision")).toHaveLength(1);
			expect(sent).toEqual(draft);
			expect(sent).toMatchObject({
				action: "accept",
				release_id: fresh.preview!.release_id,
				game: "video game music",
			});

			expect(
				await screen.findByRole(
					"button",
					{ name: "Update preview (identifying)" },
					WAIT,
				),
			).toBeDisabled();
			await statusSaying(/identifying/);

			// identify finishes with a new title and the decision the page sent.
			const next = entry(soundtrackChoice);
			next.decision = "accept";
			next.game = "video game music";
			next.holds = [];
			for (const file of next.files)
				file.after.TALB = ["Score Album (Game Music)"];
			served = view(next, {
				decision: sent!,
				approvable: { ok: true, reason: null, code: null, hold: null },
			});

			expect(
				await screen.findByRole(
					"heading",
					{ name: "Score Album (Game Music)" },
					WAIT,
				),
			).toBeInTheDocument();
			expect(
				screen.getByRole("button", { name: "Update preview" }),
			).toBeEnabled();
			// Nothing unsent is left, so Approve is on offer.
			expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
			expect(
				screen.getByRole("radio", { name: "video game music" }),
			).toBeChecked();
			expect(screen.queryByRole("alert")).not.toBeInTheDocument();
		});

		it.each([
			[400, "release not found: 0000"],
			[409, "a musiclib process is running for this album"],
		])(
			"shows a %i refusal of the decision and keeps the change on screen",
			async (status, error) => {
				const { user, region } = await show(freshScore(), {
					[`POST ${ALBUM}/decision`]: () => json({ error }, status),
				});

				await user.click(
					within(region).getByRole("radio", { name: "neither" }),
				);
				await user.click(
					within(region).getByRole("button", { name: "Update preview" }),
				);

				expect(await screen.findByRole("alert", {}, WAIT)).toHaveTextContent(
					error,
				);
				expect(
					within(region).getByRole("radio", { name: "neither" }),
				).toBeChecked();
				expect(approve(region)).toHaveAccessibleName(
					"Approve: update the preview first",
				);
				expect(
					within(region).getByRole("button", { name: "Update preview" }),
				).toBeEnabled();
			},
		);

		it("shows identify's refusal of the decision and keeps the change on screen", async () => {
			const fresh = freshScore();
			const { user, region } = await show(fresh, {
				[`POST ${ALBUM}/decision`]: identifying,
			});

			await user.click(within(region).getByRole("radio", { name: "neither" }));
			await user.click(
				within(region).getByRole("button", { name: "Update preview" }),
			);
			await screen.findByRole(
				"button",
				{ name: "Update preview (identifying)" },
				WAIT,
			);

			// identify refused: the old preview stays, with the engine's message.
			served = { ...fresh, error: REFUSED };

			expect(await screen.findByRole("alert", {}, WAIT)).toHaveTextContent(
				REFUSED,
			);
			expect(screen.getByRole("radio", { name: "neither" })).toBeChecked();
			expect(
				approve(screen.getByRole("region", { name: "Actions" })),
			).toHaveAccessibleName("Approve: update the preview first");
		});

		it("can be reached and pressed from the keyboard", async () => {
			const { user, region } = await show(freshClean(), {
				[`POST ${ALBUM}/decision`]: identifying,
			});
			const button = within(region).getByRole("button", {
				name: "Update preview",
			});

			for (let i = 0; i < 10 && document.activeElement !== button; i++)
				await user.tab();
			expect(button).toHaveFocus();
			await user.keyboard("{Enter}");

			await statusSaying(/identifying/);
			expect(posts("/decision")).toHaveLength(1);
		});
	});

	describe("when Approve is offered (criteria 29, 30)", () => {
		it("disables Approve with `update the preview first` while a change is unsent", async () => {
			const { user, region } = await show(acceptedScore());
			expect(approve(region)).toBeEnabled();

			await user.click(within(region).getByRole("radio", { name: "neither" }));
			expect(approve(region)).toBeDisabled();
			expect(approve(region)).toHaveAccessibleName(
				"Approve: update the preview first",
			);

			// Back to what the preview reflects: nothing unsent is left.
			await user.click(
				within(region).getByRole("radio", { name: "soundtrack" }),
			);
			expect(approve(region)).toBeEnabled();
			expect(approve(region)).toHaveAccessibleName("Approve");
		});

		it("names the unsent change before the server's reason on a fresh album", async () => {
			const { user, region } = await show(freshScore());
			expect(approve(region)).toHaveAccessibleName(`Approve: ${NOT_ACCEPTED}`);

			await user.click(within(region).getByRole("radio", { name: "neither" }));
			expect(approve(region)).toHaveAccessibleName(
				"Approve: update the preview first",
			);
		});

		it("disables Approve with the hold that stops it", async () => {
			const { region } = await show(heldView());

			expect(approve(region)).toBeDisabled();
			expect(approve(region)).toHaveAccessibleName(`Approve: ${HELD}`);
			expectNoServerText(region);
		});

		it("disables Approve on a preview nobody has accepted yet", async () => {
			const { region } = await show(freshClean());

			expect(approve(region)).toBeDisabled();
			expect(approve(region)).toHaveAccessibleName(`Approve: ${NOT_ACCEPTED}`);
			expectNoServerText(region);
		});

		it("disables Approve, naming the state, while a job runs", async () => {
			const { region } = await show(
				acceptedClean({
					state: "queued",
					busy: true,
					approvable: {
						ok: false,
						reason: SERVER_TEXT,
						code: "busy",
						hold: null,
					},
				}),
			);

			expect(approve(region)).toBeDisabled();
			expect(approve(region)).toHaveAccessibleName("Approve: queued");
			expectNoServerText(region);
		});

		it("offers no Approve when the album is already in the library", async () => {
			const clean = acceptedClean();
			const copy = {
				folder: LIBRARY_PATH,
				format: "MP3",
				lossless: false,
				bit_depth: null,
				sample_rate: 44100,
				bitrate: 320000,
				files: 3,
				length: 555,
				size: 22_000_000,
				cover: null,
			};
			const { region } = await show({
				...clean,
				duplicate: {
					new: copy,
					library: copy,
					recommended: "library",
					rule: SERVER_TEXT,
					rule_code: "library",
				},
			});

			expect(
				within(region).queryByRole("button", { name: /^Approve/ }),
			).not.toBeInTheDocument();
		});
	});

	describe("Approve (criteria 39, 41, 43)", () => {
		it("posts an empty approve, then shows applying and the album's path in the library", async () => {
			const clean = acceptedClean();
			const { user, region } = await show(clean, {
				[`POST ${ALBUM}/approve`]: () => {
					served = { ...served, state: "applying", busy: true };
					return json(
						{
							state: "applying",
							path: null,
							error: null,
							step: null,
							file: null,
						},
						202,
					);
				},
			});

			await user.click(approve(region));

			expect(posts("/approve")).toHaveLength(1);
			expect(JSON.parse(posts("/approve")[0].body)).toEqual({});
			await statusSaying(/applying/);

			served = {
				...clean,
				state: "in the library",
				busy: false,
				library_path: LIBRARY_PATH,
				approvable: {
					ok: false,
					reason: SERVER_TEXT,
					code: "in-library",
					hold: null,
				},
			};

			expect(await statusSaying(/in the library/)).toHaveTextContent(
				LIBRARY_PATH,
			);
		});

		it("shows apply's stderr as it came, and still offers Discard", async () => {
			const stderr =
				'Traceback (most recent call last):\n  File "apply.py", line 88\nOSError: [Errno 28] No space left on device';
			const { region } = await show(
				acceptedClean({
					state: "apply failed",
					stderr,
					approvable: {
						ok: false,
						reason: SERVER_TEXT,
						code: "not-ready",
						hold: null,
					},
				}),
			);

			const alert = within(region).getByRole("alert");
			// Line breaks are the message: a traceback folded onto one line is unreadable.
			const block = within(alert).getByText(stderr, {
				normalizer: getDefaultNormalizer({
					trim: false,
					collapseWhitespace: false,
				}),
			});
			expect(block.tagName).toBe("PRE");
			expect(
				within(region).getByRole("button", { name: "Discard" }),
			).toBeEnabled();
		});

		it("shows a failed move with the error and moves on Move into the library", async () => {
			const error = "rename failed: [Errno 18] Invalid cross-device link";
			const written = acceptedClean({
				state: "written, not moved",
				error,
				approvable: {
					ok: false,
					reason: SERVER_TEXT,
					code: "not-ready",
					hold: null,
				},
			});
			const { user, region } = await show(written, {
				[`POST ${ALBUM}/move`]: () => {
					served = { ...written, state: "in the library", error: null };
					return json({
						state: "in the library",
						path: LIBRARY_PATH,
						error: null,
						step: null,
						file: null,
					});
				},
			});

			const alert = within(region).getByRole("alert");
			expect(alert).toHaveTextContent(error);
			await user.click(
				within(region).getByRole("button", { name: "Move into the library" }),
			);

			expect(posts("/move")).toHaveLength(1);
			expect(await statusSaying(/in the library/)).toHaveTextContent(
				LIBRARY_PATH,
			);
		});
	});

	describe("after a replace that was rolled back (criteria 41, 49)", () => {
		it("shows the failed step and file, and still offers Move into the library", async () => {
			const error =
				"the SHA-256 of 03. Track.flac in the library differs from the one recorded";
			const rolledBack = acceptedClean({
				state: "written, not moved",
				error,
				step: 4,
				file: "03. Track.flac",
				approvable: {
					ok: false,
					reason: SERVER_TEXT,
					code: "not-ready",
					hold: null,
				},
			});
			const { user, region } = await show(rolledBack, {
				[`POST ${ALBUM}/move`]: () => {
					served = {
						...rolledBack,
						state: "in the library",
						error: null,
						step: null,
						file: null,
						library_path: LIBRARY_PATH,
					};
					return json({
						state: "in the library",
						path: LIBRARY_PATH,
						error: null,
						step: null,
						file: null,
					});
				},
			});

			const alert = within(region).getByRole("alert");
			expect(alert).toHaveTextContent(error);
			expect(alert).toHaveTextContent("step 4 failed on 03. Track.flac");
			const move = within(region).getByRole("button", {
				name: "Move into the library",
			});
			expect(move).toBeEnabled();
			expectNoServerText(region);

			await user.click(move);
			expect(posts("/move")).toHaveLength(1);
			expect(await statusSaying(/in the library/)).toHaveTextContent(
				LIBRARY_PATH,
			);
		});
	});

	describe("Discard (criterion 45)", () => {
		it("posts a discard for the album", async () => {
			const { user, region } = await show(freshClean(), {
				[`POST ${ALBUM}/discard`]: () => new Response(null, { status: 204 }),
			});

			await user.click(within(region).getByRole("button", { name: "Discard" }));

			expect(posts("/discard")).toHaveLength(1);
		});

		it("is disabled, saying why, while a process runs for the album", async () => {
			const { region } = await show({
				...freshClean(),
				state: "identifying",
				busy: true,
			});

			const discard = within(region).getByRole("button", { name: /^Discard/ });
			expect(discard).toBeDisabled();
			expect(discard).toHaveAccessibleName("Discard: a process is running");
		});
	});

	describe("names (criterion 57)", () => {
		it.each([
			["a fresh album with the soundtrack choice", freshScore],
			["an accepted album", acceptedClean],
			[
				"an album being identified",
				() => ({ ...freshScore(), state: "identifying" as const, busy: true }),
			],
			[
				"a finished album that did not move",
				() =>
					acceptedClean({
						state: "written, not moved",
						error: "rename failed",
						approvable: {
							ok: false,
							reason: SERVER_TEXT,
							code: "not-ready",
							hold: null,
						},
					}),
			],
		])("names every control on %s", async (_, make) => {
			const { region } = await show(make());

			const buttons = within(region).getAllByRole("button");
			expect(buttons.length).toBeGreaterThan(0);
			for (const button of buttons) expect(button).toHaveAccessibleName(/\S/);
			for (const group of within(region).queryAllByRole("radiogroup")) {
				expect(group).toHaveAccessibleName("Soundtrack");
			}
			for (const radio of within(region).queryAllByRole("radio")) {
				expect(radio).toHaveAccessibleName(/\S/);
			}
			expectNoServerText(region);
		});
	});
});
