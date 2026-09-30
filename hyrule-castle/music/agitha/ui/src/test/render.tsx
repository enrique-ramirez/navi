import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	createMemoryHistory,
	createRootRoute,
	createRoute,
	createRouter,
	RouterProvider,
} from "@tanstack/react-router";
import { type RenderResult, render } from "@testing-library/react";
import type { ReactElement } from "react";

export { screen, waitFor, within } from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";

export function renderWithProviders(
	ui: ReactElement,
	{ route = "/" }: { route?: string } = {},
): RenderResult {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const rootRoute = createRootRoute();
	const catchAll = createRoute({
		getParentRoute: () => rootRoute,
		path: "$",
		component: () => ui,
	});
	const router = createRouter({
		routeTree: rootRoute.addChildren([catchAll]),
		history: createMemoryHistory({ initialEntries: [route] }),
	});

	// The locale and theme are module stores that start on first use, so nothing wraps them here.
	return render(
		<QueryClientProvider client={queryClient}>
			<RouterProvider router={router} />
		</QueryClientProvider>,
	);
}
