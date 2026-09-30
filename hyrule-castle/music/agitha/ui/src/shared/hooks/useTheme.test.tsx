import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Scheme = "light" | "dark";

type Listener = (event: { matches: boolean; media: string }) => void;

// jsdom has no matchMedia. This one answers `prefers-color-scheme` queries for
// either scheme, so the hook may ask for light or for dark, and it tells every
// list it handed out when the system flips.
function fakeSystem(initial: Scheme) {
	let scheme = initial;
	const fires: Array<() => void> = [];

	vi.stubGlobal("matchMedia", (query: string) => {
		const wanted = /prefers-color-scheme:\s*(light|dark)/.exec(query)?.[1];
		const listeners = new Set<Listener>();
		const list = {
			media: query,
			get matches() {
				return wanted === scheme;
			},
			onchange: null as Listener | null,
			addEventListener: (_type: string, listener: Listener) =>
				listeners.add(listener),
			removeEventListener: (_type: string, listener: Listener) =>
				listeners.delete(listener),
			addListener: (listener: Listener) => listeners.add(listener),
			removeListener: (listener: Listener) => listeners.delete(listener),
			dispatchEvent: () => true,
		};
		fires.push(() => {
			const event = { matches: list.matches, media: query };
			for (const listener of listeners) listener(event);
			list.onchange?.(event);
		});
		return list;
	});

	return {
		switchTo(next: Scheme) {
			scheme = next;
			act(() => {
				for (const fire of fires) fire();
			});
		},
	};
}

// Each call is a fresh page load: new modules, the same localStorage, a new
// tab's sessionStorage and an `<html>` without the attribute a previous load set.
async function openPage() {
	vi.resetModules();
	delete document.documentElement.dataset.theme;
	sessionStorage.clear();

	const { useTheme } = await import("@/shared/hooks/useTheme");
	const { renderWithProviders, screen, userEvent } = await import(
		"@/test/render"
	);

	function ThemeProbe() {
		const { theme, chosen, choose, toggle } = useTheme();
		return (
			<>
				<p>{`theme ${theme}, chosen ${chosen ?? "nothing"}`}</p>
				<button type="button" onClick={() => choose("light")}>
					Pick light
				</button>
				<button type="button" onClick={() => choose("dark")}>
					Pick dark
				</button>
				<button type="button" onClick={() => choose(null)}>
					Follow the system
				</button>
				<button type="button" onClick={() => toggle()}>
					Toggle
				</button>
			</>
		);
	}

	const view = renderWithProviders(<ThemeProbe />);
	const user = userEvent.setup();

	return {
		async shows(theme: Scheme, chosen: Scheme | "nothing") {
			expect(
				await screen.findByText(`theme ${theme}, chosen ${chosen}`),
			).toBeInTheDocument();
			await vi.waitFor(() =>
				expect(document.documentElement).toHaveAttribute("data-theme", theme),
			);
		},
		async click(name: string) {
			await user.click(await screen.findByRole("button", { name }));
		},
		close: () => view.unmount(),
	};
}

beforeEach(() => {
	localStorage.clear();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("useTheme", () => {
	it("shows the dark theme when the system asks for dark and nothing is picked", async () => {
		fakeSystem("dark");
		const page = await openPage();

		await page.shows("dark", "nothing");
	});

	it("shows the light theme when the system asks for light and nothing is picked", async () => {
		fakeSystem("light");
		const page = await openPage();

		await page.shows("light", "nothing");
	});

	it("follows the system when it changes scheme while the page is open", async () => {
		const system = fakeSystem("dark");
		const page = await openPage();
		await page.shows("dark", "nothing");

		system.switchTo("light");
		await page.shows("light", "nothing");

		system.switchTo("dark");
		await page.shows("dark", "nothing");
	});

	it("keeps the picked theme when the system changes afterwards", async () => {
		const system = fakeSystem("dark");
		const page = await openPage();

		await page.click("Pick dark");
		await page.shows("dark", "dark");

		system.switchTo("light");
		await page.shows("dark", "dark");
	});

	it("keeps a pick against the system across a reload", async () => {
		fakeSystem("dark");
		const first = await openPage();
		await first.click("Pick light");
		await first.shows("light", "light");
		first.close();

		const second = await openPage();
		await second.shows("light", "light");
	});

	it("keeps a dark pick across a reload on a light system", async () => {
		// The mirror of the case above, so a stored pick that only ever reads
		// back as "light" is caught.
		fakeSystem("light");
		const first = await openPage();
		await first.click("Pick dark");
		await first.shows("dark", "dark");
		first.close();

		const second = await openPage();
		await second.shows("dark", "dark");
	});

	it("follows the system again once the pick is cleared, and after a reload", async () => {
		const system = fakeSystem("dark");
		const first = await openPage();
		await first.click("Pick light");
		await first.shows("light", "light");

		await first.click("Follow the system");
		await first.shows("dark", "nothing");
		first.close();

		const second = await openPage();
		await second.shows("dark", "nothing");
		system.switchTo("light");
		await second.shows("light", "nothing");
	});

	it("toggles to the other theme and keeps that as the pick", async () => {
		fakeSystem("dark");
		const page = await openPage();
		await page.shows("dark", "nothing");

		await page.click("Toggle");
		await page.shows("light", "light");

		// A second toggle is a pick of dark, not a return to following the system.
		await page.click("Toggle");
		await page.shows("dark", "dark");
	});

	it("toggles away from what the system shows when nothing is picked", async () => {
		fakeSystem("light");
		const page = await openPage();
		await page.shows("light", "nothing");

		await page.click("Toggle");
		await page.shows("dark", "dark");
	});
});
