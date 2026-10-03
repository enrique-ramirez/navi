import { afterEach, describe, expect, it } from "vitest";

import { ECLIPTICA, posted, refusal, SONATA } from "@/test/library";
import {
	albumOf,
	closeAlbum,
	openAlbum,
	setPowerMetal,
	shown,
} from "@/test/libraryAlbum";
import { screen, waitFor, within } from "@/test/render";

afterEach(closeAlbum);

const DELETE = "/api/library/delete";

const deleteButton = () => screen.getByRole("button", { name: "Delete album" });

async function confirmDelete(user: ReturnType<typeof openAlbum>["user"]) {
	await user.click(deleteButton());
	const dialog = await screen.findByRole("alertdialog");
	await user.click(
		within(dialog).getByRole("button", { name: "Delete album" }),
	);
}

describe("Delete album", () => {
	it("asks first, naming the album and how many tracks go, and Cancel deletes nothing", async () => {
		const { calls, user } = openAlbum();
		await shown();

		await user.click(deleteButton());
		const dialog = await screen.findByRole("alertdialog");
		expect(dialog).toHaveTextContent(ECLIPTICA);
		expect(dialog).toHaveTextContent("4 tracks");
		await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

		expect(screen.queryByRole("alertdialog")).toBeNull();
		expect(posted(calls, DELETE)).toEqual([]);
	});

	it("deletes the album once confirmed and goes to its artist", async () => {
		const { calls, place, user } = openAlbum();
		await shown();

		await confirmDelete(user);

		await waitFor(() => expect(place()).toBe(`/library/${SONATA}`));
		expect(posted(calls, DELETE)).toEqual([{ path: ECLIPTICA }]);
	});

	it("goes without asking to leave, where the page held a draft", async () => {
		const { place, user } = openAlbum();
		await shown();
		await setPowerMetal(user);

		await confirmDelete(user);

		await waitFor(() => expect(place()).toBe(`/library/${SONATA}`));
		expect(screen.queryByRole("alertdialog")).toBeNull();
	});

	it("shows the server's refusal as served and stays on the album", async () => {
		const { place, user } = openAlbum({
			writes: { delete: refusal(409, "the album is being saved") },
		});
		await shown();

		await confirmDelete(user);

		expect(await screen.findByText("the album is being saved")).toBeVisible();
		expect(place()).toBe(`/library/${ECLIPTICA}`);
	});

	it("is not offered while the album is open in review", async () => {
		openAlbum({
			shelves: {
				albums: {
					[ECLIPTICA]: albumOf({ match: { drop: "20261002-1", n: "01" } }),
				},
			},
		});
		await screen.findByRole("heading", { name: /Ecliptica/ });

		await waitFor(() => expect(deleteButton()).toBeDisabled());
	});
});
