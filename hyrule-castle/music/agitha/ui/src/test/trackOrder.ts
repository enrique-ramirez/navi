import { act } from "@testing-library/react";
import { vi } from "vitest";

import type { LibraryOrder, OrderFlag } from "@/shared/api/types";
import orderFixture from "@/test/fixtures/library/order.json";
import uncheckedFixture from "@/test/fixtures/library/order-unchecked.json";

import type { Call } from "./fakeFetch";
import { box, openAlbum, TITLES } from "./libraryAlbum";
import { screen, type userEvent } from "./render";

type User = ReturnType<typeof userEvent.setup>;

/** `order.json`: 8th Commandment and Replica each run the other's length. */
export const FLAGGED = orderFixture as LibraryOrder & { checked: true };
/** `order-unchecked.json`: the album has no release, and asking again will not help. */
export const UNCHECKED = uncheckedFixture as LibraryOrder & { checked: false };

/** An order that was checked, with the pairs it flags. */
export const checked = (...flags: OrderFlag[]): LibraryOrder => ({
	checked: true,
	flags,
});

/** The three sentences of an order that was not checked. Only the last may be asked again. */
export const NO_RELEASE = "Track order not checked: no MusicBrainz release";
export const NO_FIT =
	"Track order not checked: the files do not fit the release's track list";
export const NO_ANSWER = "Track order not checked: MusicBrainz did not answer";

export const unchecked = (reason: string): LibraryOrder => ({
	checked: false,
	reason,
	retry: reason === NO_ANSWER,
});

/** What the order route answers: a body, or a function for an answer that fails or waits. */
export type OrderAnswer = LibraryOrder | (() => Response | Promise<Response>);

const ORDER_ROUTE = /^\/api\/library\/[^/]+\/[^/]+\/[^/]+\/order$/;

const isOrder = (call: { method: string; url: string }) =>
	call.method === "GET" && ORDER_ROUTE.test(new URL(call.url).pathname);

/** The order requests the page made, as the album each one names, decoded. */
export function orderGets(calls: Call[]) {
	return calls.filter(isOrder).map((call) =>
		decodeURIComponent(new URL(call.url).pathname)
			.replace(/^\/api\/library\//, "")
			.replace(/\/order$/, ""),
	);
}

/** Where a request sits among the calls, or -1 where it was never made. */
export const orderAt = (calls: Call[]) => calls.findIndex(isOrder);

/**
 * The album page as `openAlbum` gives it, with the order route answering too.
 * `order` is one answer, or a list for a route asked more than once: each
 * request takes the next, and the last one repeats. With none, the order was
 * checked and flags nothing.
 *
 * `openAlbum` cannot take a fourth segment, so the route is laid over its
 * fake once the page is mounted. A page that asks for the order in the same
 * tick it mounts gets past this; the page makes the lookup after the album
 * shows.
 */
export function openOrdered({
	order = checked(),
	...opened
}: Parameters<typeof openAlbum>[0] & {
	order?: OrderAnswer | OrderAnswer[];
} = {}) {
	const page = openAlbum(opened);
	if (orderAt(page.calls) !== -1)
		throw new Error("the order was asked for before the album had answered");

	const answers = Array.isArray(order) ? [...order] : [order];
	const read: Promise<void>[] = [];
	const under = globalThis.fetch;

	vi.stubGlobal(
		"fetch",
		async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = new URL(
				String(input instanceof Request ? input.url : input),
				"http://localhost",
			);
			const method = (
				init?.method ?? (input instanceof Request ? input.method : "GET")
			).toUpperCase();
			if (!isOrder({ method, url: url.href })) return under(input, init);

			page.calls.push({ method, url: url.href, body: "" });
			const answer = answers.length > 1 ? answers.shift()! : answers[0]!;
			let done = () => {};
			read.push(
				new Promise<void>((resolve) => {
					done = resolve;
				}),
			);
			try {
				const response =
					typeof answer === "function" ? await answer() : Response.json(answer);
				return told(response, done);
			} catch (error) {
				done();
				throw error;
			}
		},
	);

	return {
		...page,
		/**
		 * Resolves once the page has read every order answer so far and has
		 * drawn what it makes of them. For a case that asserts the answer left
		 * nothing on the page, where there is no text to wait for.
		 */
		async orderSettled() {
			await vi.waitFor(() => {
				if (read.length === 0) throw new Error("no order request yet");
			});
			await Promise.all(read);
			// The query hands its answer to the page a task later, and the page
			// draws it when `act` closes. Two turns: the first may be queued
			// before the query's own.
			await act(async () => {
				await new Promise((resolve) => setTimeout(resolve, 0));
				await new Promise((resolve) => setTimeout(resolve, 0));
			});
		},
	};
}

// A response that says when its body was read. One that is not `ok` may never be read.
function told(response: Response, done: () => void) {
	if (!response.ok) {
		done();
		return response;
	}
	const json = response.json.bind(response);
	const text = response.text.bind(response);
	response.json = async () => {
		try {
			return await json();
		} finally {
			done();
		}
	};
	response.text = async () => {
		try {
			return await text();
		} finally {
			done();
		}
	};
	return response;
}

/** Leaves exactly these tracks selected, whatever was selected before. */
export async function selectOnly(user: User, ...titles: string[]) {
	for (const title of TITLES) {
		const each = box(title) as HTMLInputElement;
		if (each.checked !== titles.includes(title)) await user.click(each);
	}
}

const usableButton = (button: HTMLElement) =>
	!(button as HTMLButtonElement).disabled &&
	button.getAttribute("aria-disabled") !== "true";

/** The selection's own Swap, or `null` where it is absent or disabled. */
export function swapOffered() {
	return (
		screen.queryAllByRole("button", { name: "Swap" }).find(usableButton) ?? null
	);
}

/** Everything the page says about one track: its row, and whatever the row or its checkbox is described by. */
export function saidOf(title: string) {
	const checkbox = box(title);
	const row = checkbox.closest<HTMLElement>(
		"tr, li, [role=row], [role=listitem]",
	);
	if (!row) throw new Error(`${title} is not in a row or a list item`);
	const described = [row, checkbox]
		.flatMap((each) =>
			(each.getAttribute("aria-describedby") ?? "").split(/\s+/),
		)
		.filter((id) => id !== "")
		.map((id) => document.getElementById(id)?.textContent ?? "");
	return [row.textContent ?? "", ...described]
		.join(" ")
		.replace(/\s+/g, " ")
		.trim();
}
