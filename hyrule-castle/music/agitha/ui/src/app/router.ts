import {
	createRootRoute,
	createRoute,
	createRouter,
	type RouterHistory,
} from "@tanstack/react-router";

import { AlbumPage } from "@/features/album/AlbumPage";
import { App } from "./App";
import { Home } from "./Home";
import { NotFound } from "./NotFound";

const rootRoute = createRootRoute({
	component: App,
	notFoundComponent: NotFound,
});

const home = createRoute({
	getParentRoute: () => rootRoute,
	path: "/",
	component: Home,
});

const album = createRoute({
	getParentRoute: () => rootRoute,
	path: "/drops/$drop/albums/$n",
	component: AlbumPage,
});

const routeTree = rootRoute.addChildren([home, album]);

export function createAppRouter(history?: RouterHistory) {
	return createRouter({ routeTree, history });
}
