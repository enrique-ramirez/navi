import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// A build needs no target: the server serves the page and answers `/api` from one origin.
// Only the dev server has to be told where agitha runs.
export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), "");
	const target =
		process.env.AGITHA_URL || env.AGITHA_URL || "http://localhost:8882";

	return {
		plugins: [react()],

		resolve: {
			alias: {
				"@": fileURLToPath(new URL("./src", import.meta.url)),
			},
		},

		base: "/",

		server: {
			port: 8124,
			strictPort: true,
			proxy: {
				"/api": { target, changeOrigin: true },
			},
		},
	};
});
