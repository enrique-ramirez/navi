import { beforeAll, describe, expect, it } from "vitest";

type Catalogue = Record<string, unknown>;

let english: Catalogue;
let spanish: Catalogue;

// Globs rather than imports, so a missing file fails each case below with its
// name instead of failing the file with none.
const EN = "/src/shared/i18n/en.ts";
const ES = "/public/locales/es.json";
const ENGLISH = import.meta.glob<Catalogue>("/src/shared/i18n/en.ts", {
	import: "en",
});
const SPANISH = import.meta.glob<Catalogue>("/public/locales/es.json", {
	import: "default",
});

async function load(
	files: Record<string, () => Promise<Catalogue>>,
	path: string,
) {
	const loader = files[path];
	if (loader === undefined) throw new Error(`${path} is missing`);
	return loader();
}

beforeAll(async () => {
	english = await load(ENGLISH, EN);
	spanish = await load(SPANISH, ES);
});

const placeholdersIn = (phrase: unknown) => [
	...new Set(
		[...String(phrase).matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort(),
	),
];

describe("the catalogues", () => {
	it("give every English key a Spanish phrase", () => {
		const missing = Object.keys(english).filter(
			(key) => !Object.hasOwn(spanish, key),
		);

		expect(missing, "keys es.json lacks").toEqual([]);
	});

	it("carry no Spanish key the English catalogue lacks", () => {
		const extra = Object.keys(spanish).filter(
			(key) => !Object.hasOwn(english, key),
		);

		expect(extra, "keys only es.json has").toEqual([]);
	});

	it("hold a non-empty phrase for every key in both languages", () => {
		const empty = [
			...Object.entries(english).map(([key, phrase]) => ["en", key, phrase]),
			...Object.entries(spanish).map(([key, phrase]) => ["es", key, phrase]),
		]
			.filter(([, , phrase]) => typeof phrase !== "string" || !phrase.trim())
			.map(([language, key]) => `${language} ${key}`);

		expect(empty, "keys with no phrase").toEqual([]);
	});

	it("name the same {placeholders} in a key's Spanish as in its English", () => {
		const differ = Object.keys(english)
			.filter((key) => Object.hasOwn(spanish, key))
			.map((key) => ({
				key,
				en: placeholdersIn(english[key]),
				es: placeholdersIn(spanish[key]),
			}))
			.filter(({ en, es }) => en.join(" ") !== es.join(" "));

		expect(differ, "keys whose placeholders differ").toEqual([]);
	});
});
