import { File as NodeFile } from "node:buffer";

// user-event has no drag and drop, so the drop itself is dispatched with fireEvent.
import { fireEvent } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type {
	AlbumView,
	CoverUploadResponse,
	PlanEntry,
} from "@/shared/api/types";
import { fakeFetch } from "@/test/fakeFetch";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import {
	renderWithProviders,
	screen,
	userEvent,
	waitFor,
	within,
} from "@/test/render";

import { CoverDrop } from "./CoverDrop";
import { usePending } from "./pending";

const DROP = "20260929-210000";
const COVER_URL = `/api/drops/${DROP}/albums/01/cover`;

function view(): AlbumView {
	const entry = structuredClone(autoClean.albums[0]) as PlanEntry;
	return {
		drop: DROP,
		n: "01",
		name: "Clean Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview: entry,
		files: [],
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: `/srv/music/library/${entry.destination}`,
		tree: [],
		extras_to: [],
		decision: null,
		cover: {
			url: COVER_URL,
			width: 600,
			height: 600,
			passes: true,
			problem: null,
		},
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

// A PNG signature and bytes that are not UTF-8, so a body sent as text shows.
const PNG_BYTES = new Uint8Array([
	0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff, 0xfe, 0x80, 0x7f,
]);
const JPEG_BYTES = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a]);

// jsdom's File cannot be a fetch body under Node, so the test hands out Node's,
// as a browser hands out its own.
function image(
	name: string,
	bytes: Uint8Array<ArrayBuffer>,
	type: string,
): File {
	return new NodeFile([bytes], name, { type }) as unknown as File;
}

const PASSES: CoverUploadResponse = {
	width: 600,
	height: 600,
	passes: true,
	problem: null,
	path: "owner/cover-deadbeef.png",
};
const FAILS: CoverUploadResponse = {
	width: 400,
	height: 300,
	passes: false,
	problem: "the shorter side is 300 px, under 500",
	path: "owner/cover-0badf00d.png",
};

type Sent = {
	url: string;
	method: string;
	type: string | null;
	bytes: number[];
};

let server: ReturnType<typeof fakeFetch> | undefined;

function serve(answer: () => Response) {
	const sent: Sent[] = [];
	server = fakeFetch({
		"PUT /api/drops/:drop/albums/:n/cover": async (req) => {
			sent.push({
				url: new URL(req.url).pathname,
				method: req.method,
				type: req.headers.get("content-type"),
				bytes: [...new Uint8Array(await req.arrayBuffer())],
			});
			return answer();
		},
	});
	return { sent, calls: server.calls };
}

afterEach(() => {
	server?.restore();
	server = undefined;
});

// jsdom has no object URLs. The page may show the new cover through one, or
// through the cover's URL with a cache-busting query: either is fine, so both
// have to work here.
const original = {
	create: URL.createObjectURL,
	revoke: URL.revokeObjectURL,
};
beforeAll(() => {
	let made = 0;
	URL.createObjectURL = () => `blob:http://localhost/owner-cover-${++made}`;
	URL.revokeObjectURL = () => {};
});
afterAll(() => {
	URL.createObjectURL = original.create;
	URL.revokeObjectURL = original.revoke;
});

// The pending decision is state with no element of its own until Update
// preview sends it, so the harness prints it, and only a test id can reach it.
function Harness({ album }: { album: AlbumView }) {
	const pending = usePending(album);
	return (
		<>
			<CoverDrop view={album} pending={pending} />
			<pre data-testid="draft">{JSON.stringify(pending.draft)}</pre>
		</>
	);
}

function draft(): { cover?: string | null } {
	return JSON.parse(screen.getByTestId("draft").textContent ?? "null");
}

async function render() {
	renderWithProviders(<Harness album={view()} />);
	// The helper's router mounts the component after a tick.
	const region = await screen.findByRole("region", { name: "Cover" });
	const cover = () =>
		within(region).getByRole("img", { name: "Clean Album cover" });
	return { region, cover, before: cover().getAttribute("src") };
}

// A browser hands the dropped files out both ways; the page may read either.
function dropOnto(region: HTMLElement, files: File[]) {
	fireEvent.drop(region, {
		dataTransfer: {
			files,
			items: files.map((file) => ({
				kind: "file",
				type: file.type,
				getAsFile: () => file,
			})),
			types: ["Files"],
		},
	});
}

const WARNING = /this image fails the cover test/;

describe("CoverDrop", () => {
	it("puts a dropped PNG's bytes with its type, shows it as the cover and names the server's path in the pending decision", async () => {
		const { sent } = serve(() => Response.json(PASSES));
		const { region, cover, before } = await render();
		expect(before).toBe(COVER_URL);
		expect(draft().cover ?? null).toBeNull();

		dropOnto(region, [image("front.png", PNG_BYTES, "image/png")]);

		await waitFor(() => expect(draft().cover).toBe("owner/cover-deadbeef.png"));
		await waitFor(() => expect(cover().getAttribute("src")).not.toBe(before));
		expect(sent).toEqual([
			{
				url: `/api/drops/${DROP}/albums/01/cover`,
				method: "PUT",
				type: "image/png",
				bytes: [...PNG_BYTES],
			},
		]);
		expect(screen.queryByText(WARNING)).not.toBeInTheDocument();
	});

	it("takes a picked image that fails the cover test as the cover and says how it fails", async () => {
		const { sent } = serve(() => Response.json(FAILS));
		const { cover, before } = await render();

		await userEvent.upload(
			screen.getByLabelText("Pick a cover"),
			image("scan.png", PNG_BYTES, "image/png"),
		);

		const warning = await screen.findByRole("status");
		expect(warning).toHaveTextContent(
			"this image fails the cover test: the shorter side is 300 px, under 500",
		);
		expect(warning).toHaveTextContent("the owner's cover wins");
		await waitFor(() => expect(draft().cover).toBe("owner/cover-0badf00d.png"));
		await waitFor(() => expect(cover().getAttribute("src")).not.toBe(before));
		expect(sent.map(({ type, bytes }) => ({ type, bytes }))).toEqual([
			{ type: "image/png", bytes: [...PNG_BYTES] },
		]);
	});

	// The path is the server's to choose; one the page tidies (`.jpeg` to
	// `.jpg`) or rebuilds from the file's type names a file that is not there.
	it("names a picked JPEG by the path the server answered, as it answered it", async () => {
		const { sent } = serve(() =>
			Response.json({ ...PASSES, path: "owner/cover-cafebabe.jpeg" }),
		);
		await render();

		await userEvent.upload(
			screen.getByLabelText("Pick a cover"),
			image("Front Scan.JPEG", JPEG_BYTES, "image/jpeg"),
		);

		await waitFor(() =>
			expect(draft().cover).toBe("owner/cover-cafebabe.jpeg"),
		);
		expect(sent.map(({ type }) => type)).toEqual(["image/jpeg"]);
	});

	it("refuses a dropped text file in the page with `drop an image` and sends nothing", async () => {
		const { sent } = serve(() => Response.json(PASSES));
		const { region, cover, before } = await render();

		dropOnto(region, [
			new NodeFile(["liner notes"], "notes.txt", {
				type: "text/plain",
			}) as unknown as File,
		]);

		expect(await screen.findByRole("alert")).toHaveTextContent("drop an image");
		expect(cover().getAttribute("src")).toBe(before);
		expect(draft().cover ?? null).toBeNull();

		// A good drop after it bounds the wait: had the text file been sent, its
		// PUT would sit in the log ahead of this one.
		dropOnto(region, [image("front.png", PNG_BYTES, "image/png")]);
		await waitFor(() => expect(draft().cover).toBe("owner/cover-deadbeef.png"));
		expect(sent.map(({ type }) => type)).toEqual(["image/png"]);
	});

	it.each([415, 400])(
		"shows the server's error from a %i and leaves the cover and the pending decision alone",
		async (status) => {
			serve(() =>
				Response.json(
					{ error: "this file is not an image the server can read" },
					{ status },
				),
			);
			const { region, cover, before } = await render();

			dropOnto(region, [image("front.png", PNG_BYTES, "image/png")]);

			expect(await screen.findByRole("alert")).toHaveTextContent(
				"this file is not an image the server can read",
			);
			expect(cover().getAttribute("src")).toBe(before);
			expect(draft().cover ?? null).toBeNull();
			expect(screen.queryByText(WARNING)).not.toBeInTheDocument();
		},
	);
});
