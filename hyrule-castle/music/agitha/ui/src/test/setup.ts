import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom does not implement scrollTo and the router calls it on navigation.
window.scrollTo = () => {};

// Vitest runs without globals, so Testing Library cannot register its own cleanup.
afterEach(cleanup);
