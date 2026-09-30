import { Outlet } from "@tanstack/react-router";

import { TopBar } from "./TopBar";

export function App() {
	return (
		<>
			<TopBar />
			<Outlet />
		</>
	);
}
