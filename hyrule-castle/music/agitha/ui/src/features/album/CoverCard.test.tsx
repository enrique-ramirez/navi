import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AlbumCover, AlbumView } from "@/shared/api/types";
import { ALBUM_URL, albumView } from "@/test/albumView";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import { renderWithProviders, screen, userEvent } from "@/test/render";

import { CoverCard } from "./CoverCard";
import { type Pending, usePending } from "./pending";

const PLANNED: AlbumCover = {
	url: `${ALBUM_URL}/cover`,
	width: 600,
	height: 600,
	passes: true,
	problem: null,
};

const NOW: AlbumCover = {
	url: `${ALBUM_URL}/cover/now`,
	width: 300,
	height: 300,
	passes: false,
	problem: "the shorter side is under 500 px",
};

const BLOB = "blob:http://localhost/owner-cover";
const OWNER_PATH = "owner/cover-1a2b3c4d.png";

let latest: Pending | undefined;

function Card({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	return <CoverCard view={view} pending={pending} title="Clean Album" />;
}

const png = (name = "cover.png") =>
	new File(["png bytes"], name, { type: "image/png" });

const image = () => screen.getByRole("img", { name: "Clean Album cover" });

// Answers the upload with the cover test of what was sent.
function serveUpload(answer: { passes: boolean; problem: string | null }) {
	return fakeFetch({
		[`PUT ${ALBUM_URL}/cover`]: () =>
			Response.json({ path: OWNER_PATH, width: 400, height: 400, ...answer }),
	});
}

const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT");

describe("CoverCard", () => {
	let restore: (() => void) | undefined;
	const createObjectURL = URL.createObjectURL;
	const revokeObjectURL = URL.revokeObjectURL;

	beforeEach(() => {
		// jsdom has no object URLs.
		URL.createObjectURL = vi.fn(() => BLOB);
		URL.revokeObjectURL = vi.fn();
	});

	afterEach(() => {
		restore?.();
		restore = undefined;
		latest = undefined;
		URL.createObjectURL = createObjectURL;
		URL.revokeObjectURL = revokeObjectURL;
	});

	it("shows the cover the album will have, and the one it has now on Current", async () => {
		const user = userEvent.setup();
		renderWithProviders(
			<Card view={albumView({ cover: PLANNED, cover_now: NOW })} />,
		);

		expect(
			await screen.findByRole("img", { name: "Clean Album cover" }),
		).toHaveAttribute("src", PLANNED.url);
		expect(screen.getByText("600 × 600")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "New" })).toHaveAttribute(
			"aria-pressed",
			"true",
		);

		await user.click(screen.getByRole("button", { name: "Current" }));

		expect(image()).toHaveAttribute("src", NOW.url);
		expect(screen.getByText("300 × 300")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Current" })).toHaveAttribute(
			"aria-pressed",
			"true",
		);
		// The test is about the cover that will be written, not the one the files have.
		expect(screen.queryByRole("status")).not.toBeInTheDocument();
	});

	it("warns when the planned cover fails the cover test", async () => {
		renderWithProviders(<Card view={albumView({ cover: NOW })} />);

		expect(await screen.findByRole("status")).toHaveTextContent(
			"this image fails the cover test: the shorter side is under 500 px",
		);
	});

	it.each<[string, Partial<AlbumView>, "New" | "Current", string]>([
		[
			"a cover planned but not yet served",
			{ cover: null },
			"New",
			"a cover will be written; it can't be shown yet",
		],
		[
			"the files having none",
			{ cover_now: null },
			"Current",
			"the files have no cover",
		],
	])("says so when there is no image, for %s", async (_, over, side, words) => {
		const user = userEvent.setup();
		renderWithProviders(<Card view={albumView({ cover: PLANNED, ...over })} />);

		await user.click(await screen.findByRole("button", { name: side }));

		expect(screen.getByText(words)).toBeInTheDocument();
		expect(
			screen.queryByRole("img", { name: "Clean Album cover" }),
		).not.toBeInTheDocument();
	});

	it("says no cover will be written where the plan writes none", async () => {
		const view = albumView({ cover: null });
		view.preview!.images = {};
		renderWithProviders(<Card view={view} />);

		expect(
			await screen.findByText("no cover will be written"),
		).toBeInTheDocument();
	});

	it("uploads a picked image, shows it as the new cover, and warns when it fails the test", async () => {
		const fake = serveUpload({
			passes: false,
			problem: "the shorter side is under 500 px",
		});
		restore = fake.restore;
		const user = userEvent.setup();
		renderWithProviders(<Card view={albumView({ cover: PLANNED })} />);

		await user.upload(await screen.findByLabelText("Pick a cover"), png());

		expect(await screen.findByRole("status")).toHaveTextContent(
			"this image fails the cover test: the shorter side is under 500 px",
		);
		expect(puts(fake.calls)).toHaveLength(1);
		expect(new URL(puts(fake.calls)[0]!.url).pathname).toBe(
			`${ALBUM_URL}/cover`,
		);
		expect(image()).toHaveAttribute("src", BLOB);
		expect(screen.getByText(/^400 × 400/)).toBeInTheDocument();
		// The owner's cover wins even though it fails.
		expect(latest?.draft.cover).toBe(OWNER_PATH);
	});

	it("goes back to the planned cover when asked", async () => {
		restore = serveUpload({ passes: true, problem: null }).restore;
		const user = userEvent.setup();
		renderWithProviders(<Card view={albumView({ cover: PLANNED })} />);

		await user.upload(await screen.findByLabelText("Pick a cover"), png());
		await user.click(
			await screen.findByRole("button", { name: "use the planned cover" }),
		);

		expect(image()).toHaveAttribute("src", PLANNED.url);
		expect(latest?.draft.cover).toBeNull();
		expect(
			screen.queryByRole("button", { name: "use the planned cover" }),
		).not.toBeInTheDocument();
	});

	it("takes an image dropped on the cover", async () => {
		const fake = serveUpload({ passes: true, problem: null });
		restore = fake.restore;
		renderWithProviders(<Card view={albumView({ cover: PLANNED })} />);

		const zone = (await screen.findByLabelText("Pick a cover")).closest(
			"label",
		);
		fireEvent.drop(zone!, { dataTransfer: { files: [png()], items: [] } });

		await vi.waitFor(() => expect(image()).toHaveAttribute("src", BLOB));
		expect(puts(fake.calls)).toHaveLength(1);
		expect(screen.queryByRole("status")).not.toBeInTheDocument();
	});

	it("refuses a file that is not an image without uploading it", async () => {
		const fake = serveUpload({ passes: true, problem: null });
		restore = fake.restore;
		const user = userEvent.setup({ applyAccept: false });
		renderWithProviders(<Card view={albumView({ cover: PLANNED })} />);

		await user.upload(
			await screen.findByLabelText("Pick a cover"),
			new File(["%PDF"], "booklet.pdf", { type: "application/pdf" }),
		);

		expect(await screen.findByRole("alert")).toHaveTextContent("drop an image");
		expect(puts(fake.calls)).toEqual([]);
		expect(image()).toHaveAttribute("src", PLANNED.url);
	});

	it("shows the server's refusal of an upload", async () => {
		restore = fakeFetch({
			[`PUT ${ALBUM_URL}/cover`]: () =>
				Response.json(
					{ error: "the image could not be read" },
					{ status: 400 },
				),
		}).restore;
		const user = userEvent.setup();
		renderWithProviders(<Card view={albumView({ cover: PLANNED })} />);

		await user.upload(await screen.findByLabelText("Pick a cover"), png());

		expect(await screen.findByRole("alert")).toHaveTextContent(
			"the image could not be read",
		);
		expect(latest?.draft.cover ?? null).toBeNull();
	});
});
