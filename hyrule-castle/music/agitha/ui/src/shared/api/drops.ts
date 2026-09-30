import type { DropList } from "./types";

export const dropsKey = ["drops"];

export async function fetchDrops(): Promise<DropList> {
	const response = await fetch("/api/drops");
	if (!response.ok) throw new Error(String(response.status));
	return response.json();
}
