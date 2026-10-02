import {
	createRootRoute,
	createRoute,
	createRouter,
	type RouterHistory,
} from "@tanstack/react-router";

import { AlbumPage } from "@/features/album/AlbumPage";
import { Library } from "@/features/library/Library";
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

// Library is the layout of every /library address; its children render nothing
// of their own, so moving down the tree does not remount it.
const library = createRoute({
	getParentRoute: () => rootRoute,
	path: "/library",
	component: Library,
});

const libraryChildren = [
	"$letter",
	"$letter/$artist",
	"$letter/$artist/$album",
];

const routeTree = rootRoute.addChildren([
	home,
	album,
	library.addChildren(
		libraryChildren.map((path) =>
			createRoute({ getParentRoute: () => library, path }),
		),
	),
]);

export function createAppRouter(history?: RouterHistory) {
	return createRouter({ routeTree, history });
}
