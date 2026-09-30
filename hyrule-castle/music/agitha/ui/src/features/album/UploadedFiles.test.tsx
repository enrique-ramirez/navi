import { describe, expect, it } from "vitest";

import type { UploadedFile } from "@/shared/api/types";
import { albumView } from "@/test/albumView";
import { renderWithProviders, screen, userEvent, within } from "@/test/render";

import { UploadedFiles } from "./UploadedFiles";

function uploaded(
	path: string,
	disc: string,
	track: string,
	title: string,
): UploadedFile {
	return {
		path,
		family: "id3",
		tags: {
			TALB: [`Chrono Cross (Disc ${disc})`],
			TIT2: [title],
			TRCK: [`${track}/25`],
			TPOS: [disc],
		},
		format: "FLAC",
		lossless: true,
		bitrate: 900_000,
		sample_rate: 44_100,
		bit_depth: 16,
		channels: 2,
		length: 180,
		size: 20_000_000,
		audio_url: `/api/audio/${path}`,
	};
}

// An album nothing is planned for: the engine held it before choosing a release.
function unplanned() {
	const view = albumView({
		uploaded: [
			uploaded("CD1/01.flac", "1", "1", "Scars of Time"),
			uploaded("CD2/01.flac", "2", "1", "Dragon God"),
		],
	});
	view.preview!.files = [];
	view.files = [];
	return view;
}

describe("UploadedFiles", () => {
	it("lists the files as uploaded, numbered by disc and track from their tags", async () => {
		renderWithProviders(<UploadedFiles view={unplanned()} />);

		const list = await screen.findByRole("table", { name: "Uploaded files" });
		const rows = within(list).getAllByRole("row").slice(1);
		expect(rows.map((row) => row.textContent)).toEqual([
			expect.stringContaining("1-1Scars of TimeCD1/01.flac3:00"),
			expect.stringContaining("2-1Dragon GodCD2/01.flac3:00"),
		]);
	});

	it("shows every tag of the file picked, as it is now", async () => {
		const user = userEvent.setup();
		renderWithProviders(<UploadedFiles view={unplanned()} />);

		await user.click(
			await screen.findByText("Dragon God", { selector: "span" }),
		);

		const tags = screen.getByRole("table", { name: "Tags of CD2/01.flac" });
		expect(
			within(tags).getByRole("row", { name: /Album Chrono Cross \(Disc 2\)/ }),
		).toBeInTheDocument();
		expect(
			within(tags).getByRole("row", { name: /Disc number 2/ }),
		).toBeInTheDocument();
	});
});
