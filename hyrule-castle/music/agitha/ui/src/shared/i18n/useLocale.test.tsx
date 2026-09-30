import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type Call, fakeFetch } from "@/test/fakeFetch";

const SPANISH = "/locales/es.json";

function browserAsksFor(...languages: string[]) {
	vi.spyOn(navigator, "languages", "get").mockReturnValue(languages);
	vi.spyOn(navigator, "language", "get").mockReturnValue(languages[0] ?? "");
}

// Each call is a fresh page load: new modules, the same localStorage, a new
// tab's sessionStorage and an `<html>` without the `lang` a previous load set.
async function openPage({
	spanishPhrase,
	values,
}: {
	spanishPhrase?: string;
	values?: Record<string, string | number>;
} = {}) {
	vi.resetModules();
	document.documentElement.removeAttribute("lang");
	sessionStorage.clear();

	const { en } = await import("@/shared/i18n/en");
	const { useLocale } = await import("@/shared/i18n/locale");
	const { useTranslate } = await import("@/shared/i18n/useTranslate");
	const { renderWithProviders, screen, userEvent } = await import(
		"@/test/render"
	);

	// Any phrase without a placeholder will do; the fake Spanish catalogue
	// below gives every key a phrase that cannot be mistaken for English.
	const key = (Object.keys(en) as Array<keyof typeof en>).find(
		(candidate) => !String(en[candidate]).includes("{"),
	);
	if (key === undefined) throw new Error("en.ts has no phrase to show");
	const english = String(en[key]);
	const spanish = spanishPhrase ?? `español: ${String(key)}`;

	const server = fakeFetch({
		[`GET ${SPANISH}`]: () =>
			Response.json({
				...Object.fromEntries(
					Object.keys(en).map((phrase) => [phrase, `español: ${phrase}`]),
				),
				[key]: spanish,
			}),
	});

	function LocaleProbe() {
		const { active, chosen, available, choose } = useLocale();
		const { t } = useTranslate();
		return (
			<>
				<p>{`active ${active}, chosen ${chosen ?? "nothing"}`}</p>
				<p>{`available ${[...available].sort().join(" ")}`}</p>
				<p>{t(key as never, values)}</p>
				<button type="button" onClick={() => choose("es")}>
					Pick Spanish
				</button>
				<button type="button" onClick={() => choose("en")}>
					Pick English
				</button>
				<button type="button" onClick={() => choose(null)}>
					Follow the browser
				</button>
			</>
		);
	}

	const view = renderWithProviders(<LocaleProbe />);
	const user = userEvent.setup();

	return {
		english,
		spanish,
		calls: server.calls,
		async shows(
			active: "en" | "es",
			chosen: "en" | "es" | "nothing",
			phrase: string,
		) {
			expect(
				await screen.findByText(`active ${active}, chosen ${chosen}`),
			).toBeInTheDocument();
			expect(await screen.findByText(phrase)).toBeInTheDocument();
			await vi.waitFor(() =>
				expect(document.documentElement).toHaveAttribute("lang", active),
			);
		},
		async click(name: string) {
			await user.click(await screen.findByRole("button", { name }));
		},
		close: () => view.unmount(),
		screen,
	};
}

const askedForSpanish = (calls: Call[]) =>
	calls.some((call) => new URL(call.url).pathname === SPANISH);

beforeEach(() => {
	localStorage.clear();
});

afterEach(() => {
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe("useLocale", () => {
	it("shows Spanish when the browser's first language is a Spanish one", async () => {
		browserAsksFor("es-MX", "en-US");
		const page = await openPage();

		await page.shows("es", "nothing", page.spanish);
		expect(askedForSpanish(page.calls)).toBe(true);
	});

	it("shows English when the browser puts English before Spanish", async () => {
		browserAsksFor("en-GB", "es-ES");
		const page = await openPage();

		await page.shows("en", "nothing", page.english);
		expect(askedForSpanish(page.calls)).toBe(false);

		// Following the browser again after a pick must land on English too; this
		// is the check that does not depend on how soon a wrong switch would land.
		await page.click("Pick Spanish");
		await page.shows("es", "es", page.spanish);
		await page.click("Follow the browser");
		await page.shows("en", "nothing", page.english);
	});

	it("shows English when the browser asks for neither language", async () => {
		browserAsksFor("fr-FR", "de");
		const page = await openPage();

		await page.shows("en", "nothing", page.english);
		await page.click("Pick Spanish");
		await page.shows("es", "es", page.spanish);
		await page.click("Follow the browser");
		await page.shows("en", "nothing", page.english);
	});

	it("offers English and Spanish to pick from", async () => {
		browserAsksFor("en-US");
		const page = await openPage();

		expect(await page.screen.findByText("available en es")).toBeInTheDocument();
	});

	it("keeps a Spanish pick on an English browser across a reload", async () => {
		browserAsksFor("en-US");
		const first = await openPage();
		await first.click("Pick Spanish");
		await first.shows("es", "es", first.spanish);
		first.close();

		const second = await openPage();
		await second.shows("es", "es", second.spanish);
	});

	it("keeps an English pick on a Spanish browser across a reload", async () => {
		browserAsksFor("es-ES");
		const first = await openPage();
		await first.shows("es", "nothing", first.spanish);
		await first.click("Pick English");
		await first.shows("en", "en", first.english);
		first.close();

		const second = await openPage();
		await second.shows("en", "en", second.english);
	});

	it("follows the browser again once the pick is cleared, and after a reload", async () => {
		browserAsksFor("es-AR", "en");
		const first = await openPage();
		await first.click("Pick English");
		await first.shows("en", "en", first.english);

		await first.click("Follow the browser");
		await first.shows("es", "nothing", first.spanish);
		first.close();

		const second = await openPage();
		await second.shows("es", "nothing", second.spanish);
	});

	it("puts each value given into its {name} in the phrase shown", async () => {
		browserAsksFor("es-ES");
		const page = await openPage({
			spanishPhrase: "{artist} tiene {count} discos",
			values: { artist: "Nobuo Uematsu", count: 3 },
		});

		await page.shows("es", "nothing", "Nobuo Uematsu tiene 3 discos");
	});
});
