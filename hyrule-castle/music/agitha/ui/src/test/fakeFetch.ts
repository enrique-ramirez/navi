import { vi } from "vitest";

type Handler = (req: Request) => Response | Promise<Response>;

export type Call = { method: string; url: string; body: string };

// A key is "METHOD /path"; `:param` segments match any one path segment.
export function fakeFetch(handlers: Record<string, Handler>) {
	const routes = Object.entries(handlers).map(([key, handler]) => {
		const [method = "", path = ""] = key.split(" ");
		const pattern = new RegExp(
			`^${path
				.split("/")
				.map((part) => (part.startsWith(":") ? "[^/]+" : escapeRegExp(part)))
				.join("/")}$`,
		);
		return { method: method.toUpperCase(), pattern, handler };
	});
	const calls: Call[] = [];

	vi.stubGlobal(
		"fetch",
		async (input: RequestInfo | URL, init?: RequestInit) => {
			const req = new Request(
				new URL(
					String(input instanceof Request ? input.url : input),
					"http://localhost",
				),
				init,
			);
			const { pathname } = new URL(req.url);
			calls.push({
				method: req.method,
				url: req.url,
				body: await req.clone().text(),
			});
			const route = routes.find(
				(r) => r.method === req.method && r.pattern.test(pathname),
			);
			return route ? route.handler(req) : new Response(null, { status: 404 });
		},
	);

	return { calls, restore: () => vi.unstubAllGlobals() };
}

function escapeRegExp(text: string) {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
