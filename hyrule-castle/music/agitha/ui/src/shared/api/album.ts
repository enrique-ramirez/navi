import { getJson } from "./getJson";
import type { AlbumView, CoverUploadResponse } from "./types";

export const albumUrl = (view: { drop: string; n: string }) =>
	`/api/drops/${encodeURIComponent(view.drop)}/albums/${encodeURIComponent(view.n)}`;

export async function fetchAlbum(drop: string, n: string): Promise<AlbumView> {
	return getJson<AlbumView>(albumUrl({ drop, n }));
}

type Answer<Body> =
	| { ok: true; body: Body }
	| { ok: false; error: string | null; status: number };

async function answerOf<Body>(response: Response): Promise<Answer<Body>> {
	const body = (await response.json().catch(() => null)) as
		| (Body & { error?: string })
		| null;
	if (response.ok) return { ok: true, body: body as Body };
	return { ok: false, error: body?.error ?? null, status: response.status };
}

export async function post(
	url: string,
	body: unknown,
): Promise<{ ok: true; body: unknown } | { ok: false; error: string }> {
	const answer = await answerOf<unknown>(
		await fetch(url, {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(body),
		}),
	);
	if (answer.ok) return answer;
	return { ok: false, error: answer.error ?? String(answer.status) };
}

export async function putCover(view: { drop: string; n: string }, file: File) {
	return answerOf<CoverUploadResponse>(
		await fetch(`${albumUrl(view)}/cover`, {
			method: "PUT",
			headers: { "content-type": file.type },
			body: file,
		}),
	);
}
