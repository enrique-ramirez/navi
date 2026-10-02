import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { vi } from "vitest";

import { createAppRouter } from "@/app/router";

// The app's own routes at an address, as a browser opening that address has them.
// `renderWithProviders` brings a router of its own and cannot take these.
// Fake the network before calling this, and restore the fake after: its
// `restore` also takes back the `matchMedia` stubbed here.
// A case that has to ask for everything again, as a save does for what it
// changed, passes its own client and invalidates through it.
export function renderApp(
	address: string,
	client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
	// jsdom has no matchMedia, and the shell's theme asks it for the system's choice.
	vi.stubGlobal("matchMedia", (query: string) => ({
		matches: false,
		media: query,
		addEventListener: () => {},
		removeEventListener: () => {},
		addListener: () => {},
		removeListener: () => {},
		onchange: null,
		dispatchEvent: () => false,
	}));
	const router = createAppRouter(
		createMemoryHistory({ initialEntries: [address] }),
	);
	render(
		<QueryClientProvider client={client}>
			<RouterProvider router={router} />
		</QueryClientProvider>,
	);
	return router;
}
