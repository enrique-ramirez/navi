import { describe, expect, it } from "vitest";

import { Parasol } from "@/shared/ui/Parasol";
import { renderWithProviders, screen } from "@/test/render";

const FAVICON = import.meta.glob<string>("/public/favicon.svg", {
	query: "?raw",
	import: "default",
	eager: true,
})["/public/favicon.svg"];

const SHAPES = "path, circle, ellipse, line, polyline, polygon, rect";
const GEOMETRY = [
	"d",
	"cx",
	"cy",
	"r",
	"rx",
	"ry",
	"x",
	"y",
	"x1",
	"y1",
	"x2",
	"y2",
	"points",
	"width",
	"height",
	"transform",
];

// What is drawn, without how it is painted: the favicon may fill with a fixed
// colour where the component uses currentColor.
const drawingOf = (svg: Element) => ({
	viewBox: svg.getAttribute("viewBox"),
	shapes: [...svg.querySelectorAll(SHAPES)]
		.map((shape) =>
			[
				shape.localName,
				...GEOMETRY.filter((name) => shape.hasAttribute(name)).map(
					(name) => `${name}=${shape.getAttribute(name)?.trim()}`,
				),
			].join(" "),
		)
		.sort(),
});

describe("Parasol", () => {
	it("is an image named by its title when given one", async () => {
		renderWithProviders(<Parasol title="agitha" />);

		expect(
			await screen.findByRole("img", { name: "agitha" }),
		).toBeInTheDocument();
	});

	it("is hidden from assistive technology without a title", async () => {
		renderWithProviders(
			<button type="button">
				<Parasol />
				Import
			</button>,
		);

		// The button's name must be the word alone: a decorative drawing that
		// leaks a <title> or a role into it reads as noise on every control.
		const button = await screen.findByRole("button", { name: "Import" });
		expect(screen.queryByRole("img")).not.toBeInTheDocument();
		expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
	});

	it("draws the same parasol as favicon.svg", async () => {
		if (FAVICON === undefined) throw new Error("public/favicon.svg is missing");
		renderWithProviders(<Parasol title="agitha" />);

		const drawn = drawingOf(await screen.findByRole("img", { name: "agitha" }));
		const favicon = new DOMParser().parseFromString(FAVICON, "image/svg+xml");

		expect(drawn.shapes.length, "the logo draws nothing").toBeGreaterThan(0);
		expect(drawn).toEqual(drawingOf(favicon.documentElement));
	});
});
