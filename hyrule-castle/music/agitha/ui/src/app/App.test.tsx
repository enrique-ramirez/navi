import { expect, it } from "vitest";

import { App } from "@/app/App";
import { renderWithProviders, screen } from "@/test/render";

it("renders the title", async () => {
	renderWithProviders(<App />);

	expect(
		await screen.findByRole("heading", { name: "agitha", level: 1 }),
	).toBeInTheDocument();
});
