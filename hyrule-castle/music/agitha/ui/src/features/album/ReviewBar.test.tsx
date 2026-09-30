import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { albumQuery } from "@/domain/album/albumQuery";
import type { AlbumState, AlbumView } from "@/shared/api/types";
import { ALBUM_URL, albumView, DROP } from "@/test/albumView";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import {
	renderWithProviders,
	screen,
	userEvent,
	waitFor,
	within,
} from "@/test/render";

import { type Pending, usePending } from "./pending";
import { ReviewBar } from "./ReviewBar";

const ALBUM_ROUTE = `/drops/${DROP}/albums/01`;
const RELEASE = "6f1a2b3c-0000-4000-8000-000100000001";

// What the preview's own release sends when nothing was changed.
const UNCHANGED = {
	action: "accept",
	release_id: RELEASE,
	edits: {},
	game: null,
	cover: null,
};

const notAccepted = (over: Partial<AlbumView> = {}) =>
	albumView({
		approvable: {
			ok: false,
			reason: "SERVER TEXT",
			code: "not-accepted",
			hold: null,
		},
		...over,
	});

const accepted = (over: Partial<AlbumView> = {}) =>
	albumView({ decision: { ...UNCHANGED, action: "accept" }, ...over });

// The server as the bar sees it: a sent decision queues identify, which answers
// `queued`, then `identifying`, then `identified` with the decision recorded.
function serve(
	start: AlbumView,
	{ identified = accepted() }: { identified?: AlbumView } = {},
) {
	let current = start;
	let running: AlbumState[] = [];
	return fakeFetch({
		[`GET ${ALBUM_URL}`]: () => {
			const state = running.shift();
			return Response.json(state ? { ...current, state, busy: true } : current);
		},
		[`POST ${ALBUM_URL}/decision`]: async (req) => {
			const decision = await req.json();
			current = { ...identified, decision };
			running = ["queued", "identifying"];
			return Response.json({ state: "queued" });
		},
		[`POST ${ALBUM_URL}/approve`]: () => {
			current = { ...current, state: "in the library", busy: false };
			return Response.json({
				state: "in the library",
				path: current.library_path,
				error: null,
				step: null,
				file: null,
			});
		},
		[`POST ${ALBUM_URL}/move`]: () => {
			current = { ...current, state: "in the library" };
			return Response.json({ state: "in the library" });
		},
		[`POST ${ALBUM_URL}/discard`]: () => Response.json({ state: "discarded" }),
	});
}

function Where() {
	const path = useRouterState({ select: (s) => s.location.pathname });
	return <p data-testid="where">{path}</p>;
}

// The last pending the harness saw, so a case can make the draft dirty as the
// tag table or the match picker would.
let latest: Pending | undefined;

function Bar({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	return <ReviewBar view={view} pending={pending} />;
}

// The album comes from the same query as the page's, so the bar's refreshes and polls reach it.
function Page() {
	const { data } = useQuery(albumQuery(DROP, "01"));
	return data ? <Bar view={data} /> : null;
}

function renderBar() {
	return renderWithProviders(
		<>
			<Page />
			<Where />
		</>,
		{ route: ALBUM_ROUTE },
	);
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const pathOf = (call: Call) => new URL(call.url).pathname;

// Advances the clock a poll at a time until `check` passes.
async function throughPolls(check: () => void, polls = 6) {
	for (let i = 0; i < polls; i++) {
		try {
			check();
			return;
		} catch {
			await vi.advanceTimersByTimeAsync(2_100);
		}
	}
	check();
}

function editAlbumTitle() {
	act(() => latest?.setEdit("all", "TALB", ["Other Album"]));
}

describe("ReviewBar", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
		latest = undefined;
		vi.useRealTimers();
	});

	it("names the drop and the album, and shows the album's title and state", async () => {
		restore = serve(accepted()).restore;
		renderBar();

		expect(
			await screen.findByRole("heading", { name: "Clean Album" }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("link", { name: `Drop ${DROP} · album 01` }),
		).toHaveAttribute("href", "/");
		expect(screen.getByText("ready")).toBeInTheDocument();
	});

	describe("Approve on a preview not yet accepted", () => {
		it("accepts the preview as it is, and nothing can be pressed again while identify runs", async () => {
			const fake = serve(notAccepted());
			restore = fake.restore;
			const user = userEvent.setup();
			renderBar();

			const approve = await screen.findByRole("button", { name: "Approve" });
			expect(approve).toBeEnabled();
			// Not accepted is no reason to refuse: pressing Approve accepts first.
			expect(screen.queryByText(/^Approve:/)).not.toBeInTheDocument();
			await user.click(approve);

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			expect(pathOf(posts(fake.calls)[0]!)).toBe(`${ALBUM_URL}/decision`);
			expect(JSON.parse(posts(fake.calls)[0]!.body)).toEqual(UNCHANGED);

			await waitFor(() =>
				expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled(),
			);
			for (const button of screen.queryAllByRole("button", {
				name: /^Approv/,
			}))
				expect(button).toBeDisabled();
		});

		it("approves once identify has run on the accepted preview", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const fake = serve(notAccepted());
			restore = fake.restore;
			const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Approve" }));

			await throughPolls(() => expect(posts(fake.calls)).toHaveLength(2));
			expect(posts(fake.calls).map(pathOf)).toEqual([
				`${ALBUM_URL}/decision`,
				`${ALBUM_URL}/approve`,
			]);
			await throughPolls(() =>
				expect(screen.getByRole("status")).toHaveTextContent("in the library"),
			);
		});

		it("approves nothing when identify plans something other than what was on screen", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const replanned = accepted();
			replanned.preview = {
				...replanned.preview!,
				plan_digest: "a-different-plan",
			};
			const fake = serve(notAccepted(), { identified: replanned });
			restore = fake.restore;
			const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Approve" }));

			await throughPolls(() =>
				expect(screen.getByRole("alert")).toHaveTextContent(
					"Identify planned something different",
				),
			);
			expect(posts(fake.calls).map(pathOf)).toEqual([`${ALBUM_URL}/decision`]);
		});

		it("stops after accepting when identify finds the album is already in the library", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const fake = serve(notAccepted(), {
				identified: accepted({
					duplicate: {} as AlbumView["duplicate"],
				}),
			});
			restore = fake.restore;
			const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Approve" }));

			await throughPolls(() =>
				screen.getByText("Choose which copy to keep below"),
			);
			await vi.advanceTimersByTimeAsync(5_000);
			expect(posts(fake.calls).map(pathOf)).toEqual([`${ALBUM_URL}/decision`]);
			expect(
				screen.queryByRole("button", { name: "Approve" }),
			).not.toBeInTheDocument();
		});

		it("shows the server's refusal and approves nothing", async () => {
			const fake = fakeFetch({
				[`GET ${ALBUM_URL}`]: () => Response.json(notAccepted()),
				[`POST ${ALBUM_URL}/decision`]: () =>
					Response.json(
						{ error: "the release was not found" },
						{ status: 400 },
					),
			});
			restore = fake.restore;
			const user = userEvent.setup();
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Approve" }));

			expect(await screen.findByRole("alert")).toHaveTextContent(
				"the release was not found",
			);
			expect(posts(fake.calls)).toHaveLength(1);
			expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
		});
	});

	it("approves an accepted album at once", async () => {
		const fake = serve(accepted());
		restore = fake.restore;
		const user = userEvent.setup();
		renderBar();

		await user.click(await screen.findByRole("button", { name: "Approve" }));

		await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
		expect(pathOf(posts(fake.calls)[0]!)).toBe(`${ALBUM_URL}/approve`);
		expect(JSON.parse(posts(fake.calls)[0]!.body)).toEqual({});
	});

	describe("unsaved changes", () => {
		it("offers to save and re-preview instead of approving", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const fake = serve(accepted());
			restore = fake.restore;
			const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
			renderBar();

			await screen.findByRole("button", { name: "Approve" });
			editAlbumTitle();

			expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
			expect(
				screen.queryByRole("button", { name: "Approve" }),
			).not.toBeInTheDocument();
			await user.click(
				screen.getByRole("button", { name: "Save & re-preview" }),
			);

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			const [sent] = posts(fake.calls);
			expect(pathOf(sent!)).toBe(`${ALBUM_URL}/decision`);
			const edits = { TALB: ["Other Album"] };
			expect(JSON.parse(sent!.body)).toEqual({
				...UNCHANGED,
				edits: { "1-1": edits, "1-2": edits, "1-3": edits },
			});

			// Once the new preview is in, the changes are saved and nothing is approved.
			await throughPolls(() =>
				expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
			);
			expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
			await vi.advanceTimersByTimeAsync(5_000);
			expect(posts(fake.calls)).toHaveLength(1);
		});

		it("undoes the changes without sending anything", async () => {
			const fake = serve(accepted());
			restore = fake.restore;
			const user = userEvent.setup();
			renderBar();

			await screen.findByRole("button", { name: "Approve" });
			editAlbumTitle();
			await user.click(screen.getByRole("button", { name: "Undo changes" }));

			expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
			expect(
				screen.queryByRole("button", { name: "Undo changes" }),
			).not.toBeInTheDocument();
			expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
			expect(latest?.draft).toEqual(UNCHANGED);
			expect(posts(fake.calls)).toEqual([]);
		});
	});

	describe("Discard", () => {
		it("asks first, and Cancel keeps the album", async () => {
			const fake = serve(accepted());
			restore = fake.restore;
			const user = userEvent.setup();
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Discard" }));
			const dialog = screen.getByRole("alertdialog");
			expect(dialog).toHaveTextContent(
				"Discard Clean Album? Its uploaded files are deleted and can't be brought back.",
			);
			await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

			expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
			expect(posts(fake.calls)).toEqual([]);
			expect(screen.getByTestId("where")).toHaveTextContent(ALBUM_ROUTE);
		});

		it("discards the album once confirmed and goes back to the drops", async () => {
			const fake = serve(accepted());
			restore = fake.restore;
			const user = userEvent.setup();
			renderBar();

			await user.click(await screen.findByRole("button", { name: "Discard" }));
			await user.click(
				within(screen.getByRole("alertdialog")).getByRole("button", {
					name: "Discard",
				}),
			);

			await waitFor(() =>
				expect(screen.getByTestId("where").textContent).toBe("/"),
			);
			expect(posts(fake.calls).map(pathOf)).toEqual([`${ALBUM_URL}/discard`]);
		});

		it("cannot be pressed while a process runs for the album", async () => {
			restore = serve(accepted({ state: "applying", busy: true })).restore;
			renderBar();

			const discard = await screen.findByRole("button", { name: "Discard" });
			expect(discard).toBeDisabled();
			expect(discard).toHaveAttribute("title", "Discard: a process is running");
		});
	});

	it("says why an accepted album cannot be approved", async () => {
		restore = serve(
			accepted({
				approvable: {
					ok: false,
					reason: "SERVER TEXT",
					code: "held",
					hold: { kind: "collision", detail: "album 02 plans this folder" },
				},
			}),
		).restore;
		renderBar();

		const approve = await screen.findByRole("button", { name: "Approve" });
		expect(approve).toBeDisabled();
		expect(
			screen.getByText("Approve: held: collision: album 02 plans this folder"),
		).toBeInTheDocument();
		expect(screen.queryByText(/SERVER TEXT/)).not.toBeInTheDocument();
	});

	it("offers to move an album that was written but not moved", async () => {
		const fake = serve(
			accepted({ state: "written, not moved", error: "the disk is full" }),
		);
		restore = fake.restore;
		const user = userEvent.setup();
		renderBar();

		expect(await screen.findByRole("alert")).toHaveTextContent(
			"the disk is full",
		);
		await user.click(
			screen.getByRole("button", { name: "Move into the library" }),
		);

		await waitFor(() =>
			expect(posts(fake.calls).map(pathOf)).toEqual([`${ALBUM_URL}/move`]),
		);
	});

	it.each<[string, Partial<AlbumView>]>([
		["while identify runs", { state: "identifying", busy: true }],
		["once the album is in the library", { state: "in the library" }],
		["where identify failed", { state: "identify failed" }],
	])("offers no Approve %s", async (_, over) => {
		restore = serve(accepted(over)).restore;
		renderBar();

		await screen.findByRole("heading", { name: "Clean Album" });
		expect(
			screen.queryByRole("button", { name: "Approve" }),
		).not.toBeInTheDocument();
		expect(
			screen.queryByRole("button", { name: "Move into the library" }),
		).not.toBeInTheDocument();
	});
});
