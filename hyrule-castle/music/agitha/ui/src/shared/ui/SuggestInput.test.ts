import { describe, expect, it } from "vitest";

import { suggestionsFor, withPicked } from "./SuggestInput";

const GENRES = ["electro", "electro house", "electronic", "house", "trance"];

describe("suggestionsFor", () => {
	it("offers nothing until a value is being typed", () => {
		expect(suggestionsFor(GENRES, "")).toEqual([]);
		expect(suggestionsFor(GENRES, "trance; ")).toEqual([]);
	});

	it("offers the options that start with the typed value before those that only hold it", () => {
		expect(suggestionsFor(GENRES, "hou")).toEqual(["house", "electro house"]);
	});

	it("matches the value after the last separator alone, whatever its case", () => {
		expect(suggestionsFor(GENRES, "trance; ELECTRON")).toEqual(["electronic"]);
	});

	it("leaves out an option already typed", () => {
		expect(suggestionsFor(GENRES, "electro; electro")).toEqual([
			"electro house",
			"electronic",
		]);
	});
});

describe("withPicked", () => {
	it("writes the option in place of the typed value, with the separator after it", () => {
		expect(withPicked("elec", "electronic")).toBe("electronic; ");
		expect(withPicked("trance; elec", "electronic")).toBe(
			"trance; electronic; ",
		);
	});
});
